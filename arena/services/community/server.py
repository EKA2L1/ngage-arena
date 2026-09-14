"""Shared Community SOAP and Sega SNAP/XMPP services."""
import asyncio
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
import logging
import ipaddress
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

LOG = logging.getLogger(__name__)
SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
AUTH = 'jabber:iq:auth'
DOMAIN = 'ngage-arena'
from arena.xmlutil import fields, local
from arena.services.profiles.assets import DEFAULT_ICON, DEFAULT_ICON_PATH, default_icon_url


@dataclass
class CommunitySession:
    expires: float
    user: int | None = None


class CommunityServer:
    def __init__(self, store, games, trace=None, clock=time.monotonic, local_native_http=False):
        from arena.services.snap.protocol import Credentials
        self.store = store
        self.games = games
        self.snap_credentials = Credentials()
        self.trace = Path(trace) if trace else None
        self.writers = set()
        self.tasks = set()
        self.clock = clock
        self.http_sessions = {}
        self.local_native_http = local_native_http
        from arena.services.rankings.service import RankingsService
        self.rankings = RankingsService(store, games)
        from arena.services.rankings.web import RankingPages
        self.ranking_pages = RankingPages(self.rankings.points, games)
        from arena.services.catalogue.pages import CataloguePages
        self.catalogue_pages = CataloguePages(games)
        from arena.services.profiles.service import ProfileService, ProfileStore
        self.profiles = ProfileService(ProfileStore(store, point_totals=self.rankings.points.totals))
        from arena.services.messaging.service import Messaging
        self.messaging = Messaging(self.profiles.store)
        from arena.services.achievements.service import AchievementService
        self.achievements = AchievementService(store, games)

    def local_game_user(self, body, address):
        if not self.local_native_http or not ipaddress.ip_address(address).is_loopback:
            return None
        if b'<!' in body:
            raise ValueError('Unsupported XML declaration')
        root = ET.fromstring(body)
        attribute = {'rankings': 'name', 'player': 'userName'}.get(root.tag)
        if attribute is None:
            raise ValueError('Expected a game report')
        credential = self.snap_credentials.lookup(root.get(attribute, ''), address)
        return credential.user if credential else None

    async def close(self):
        for writer in tuple(self.writers):
            writer.close()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.http_sessions.clear()

    def community_session(self, header, create=True):
        now = self.clock()
        self.http_sessions = {key: value for key, value in self.http_sessions.items()
                              if value.expires > now}
        cookie = SimpleCookie()
        try:
            cookie.load(header)
        except CookieError:
            cookie.clear()
        token = cookie['JSESSIONID'].value if 'JSESSIONID' in cookie else None
        if token not in self.http_sessions:
            if not create:
                return None, None
            if len(self.http_sessions) >= 512:
                oldest = min(self.http_sessions, key=lambda key: self.http_sessions[key].expires)
                del self.http_sessions[oldest]
            token = secrets.token_hex(24)
            self.http_sessions[token] = CommunitySession(now + 3600)
        session = self.http_sessions[token]
        session.expires = now + 3600
        return token, session

    def record(self, transport, data):
        if self.trace:
            text = data.decode('utf-8', errors='replace')
            text = re.sub(r'(<(?:\w+:)?(?:password|imei|imsi|answer)\b[^>]*>).*?(</[^>]+>)',
                          r'\1REDACTED\2', text, flags=re.S | re.I)
            with self.trace.open('a') as stream:
                stream.write(transport + ' ' + text + '\n')

    def soap_response(self, body, session=None, ngi=False):
        if b'<!' in body:
            raise ValueError('Unsupported XML declaration')
        root = ET.fromstring(body)
        soap_body = root.find('{'+SOAP+'}Body')
        if soap_body is None or len(soap_body) != 1:
            raise ValueError('Expected one SOAP operation')
        operation = soap_body[0]
        method = local(operation.tag)
        params = fields(operation)
        try:
            if method == 'createUser':
                self.store.create_user(params.get('username', ''), params.get('password', ''))
                result = '<createUserResponse xmlns="urn:CommunityApp"><createUserReturn>true</createUserReturn></createUserResponse>'
            elif method == 'authenticateUser':
                user = self.store.authenticate(params.get('username', ''), params.get('password', ''))
                if session is not None:
                    session.user = user
                if ngi:
                    name = self.store.name(user) if user is not None else ''
                    result = ('<authenticateUserResponse xmlns="urn:CommunityApp"><authenticateUserReturn>'
                              '<item xsi:type="xsd:string">'+('0' if user is not None else '1')+'</item>'
                              '<item xsi:type="xsd:string">'+escape(name)+'</item>'
                              '</authenticateUserReturn></authenticateUserResponse>')
                elif user is None:
                    raise ValueError('Invalid username or password')
                else:
                    result = f'<authenticateUserResponse xmlns="urn:CommunityApp"><authenticateUserReturn>{user}</authenticateUserReturn></authenticateUserResponse>'
            elif method == 'authenticateUser2':
                user = self.store.authenticate(params.get('username', ''), params.get('password', ''))
                if session is not None:
                    session.user = user
                name = self.store.name(user) if user else None
                result = ('<authenticateUser2Response xmlns="urn:CommunityApp">'
                          '<authenticateUser2Return><item xsi:type="xsd:boolean">'
                          +('true' if name else 'false')+'</item><item xsi:type="xsd:string">'
                          +escape(name or '')+'</item></authenticateUser2Return>'
                          '</authenticateUser2Response>')
            elif method == 'checkImei':
                result = ('<checkImeiResponse xmlns="urn:CommunityApp">'
                          '<checkImeiReturn xsi:type="xsd:boolean">false</checkImeiReturn></checkImeiResponse>')
            elif method == 'HeartBeat':
                result = '<HeartBeatResponse xmlns="urn:CommunityApp"><HeartBeatReturn>true</HeartBeatReturn></HeartBeatResponse>'
            elif method == 'getNewAlertStatus':
                result = ('<getNewAlertStatusResponse xmlns="urn:CommunityApp">'
                          '<getNewAlertStatusReturn>false</getNewAlertStatusReturn></getNewAlertStatusResponse>')
            else:
                raise ValueError('Unknown Community operation')
            LOG.info('Community %s completed', method)
        except ValueError as error:
            result = '<soapenv:Fault><faultcode>soapenv:Client</faultcode><faultstring>'+escape(str(error))+'</faultstring><detail><message>'+escape(str(error))+'</message></detail></soapenv:Fault>'
        return ('<?xml version="1.0"?><soapenv:Envelope xmlns:soapenv="'+SOAP+'" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
                '<soapenv:Body>'+result+'</soapenv:Body></soapenv:Envelope>').encode()

    def snap_response(self, user, node):
        result = ET.Element('message', {'from': node.get('to', ''),
            'id': 'segachat_retrieve_resp', 'event_type': node.get('event_type', ''),
            'game_class_id': node.get('game_class_id', '')})
        try:
            if user is None:
                raise ValueError('Login required')
            payload = self.games.retrieve(user, node)
        except (ValueError, TypeError, StopIteration, ET.ParseError) as error:
            payload = '1\n'+str(error)+'\n'
        ET.SubElement(ET.SubElement(result, 'retrieve'), 'response').text = payload
        return ET.tostring(result, encoding='unicode')

    async def http(self, reader, writer):
        self.writers.add(writer)
        self.tasks.add(asyncio.current_task())
        try:
            headers = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 20)
            first, *lines = headers.decode('ascii').split('\r\n')
            method, path, *_ = first.split()
            route, _, matrix = path.partition(';')
            LOG.debug('Community HTTP %s %s', method, route.partition('?')[0])
            values = {key.lower(): value.strip() for line in lines if ':' in line
                      for key, value in [line.split(':', 1)]}
            page_path = urlsplit(route).path
            pages = (self.ranking_pages if page_path == self.ranking_pages.path else
                     self.catalogue_pages if page_path.startswith(self.catalogue_pages.prefix) else None)
            if pages:
                status = b'200 OK'
                extra = b''
                content_type = 'text/html; charset=utf-8'
                try:
                    if method not in {'GET', 'HEAD'}:
                        status, response = b'405 Method Not Allowed', b'Method not allowed'
                        extra = b'Allow: GET, HEAD\r\n'
                    else:
                        if pages is self.catalogue_pages:
                            response = pages.render(route, values.get('host', 'showroom.n-gage.com'),
                                                    bool(writer.get_extra_info('ssl_object')))
                            content_type = pages.content_type(route)
                        else:
                            response = pages.render(route)
                except ValueError:
                    status, response = b'400 Bad Request', b'Invalid page request'
                writer.write(b'HTTP/1.0 '+status+b'\r\n'+extra
                             + b'Content-Type: '+content_type.encode()+b'\r\nCache-Control: no-store\r\n'
                             + b'Connection: close\r\nContent-Length: '+str(len(response)).encode()+b'\r\n\r\n')
                if method != 'HEAD':
                    writer.write(response)
                await writer.drain()
                return
            if method in {'GET', 'HEAD'} and route == DEFAULT_ICON_PATH:
                writer.write(b'HTTP/1.0 200 OK\r\nContent-Type: image/png\r\n'
                             b'Cache-Control: public, max-age=86400\r\nConnection: close\r\n'
                             b'Content-Length: '+str(len(DEFAULT_ICON)).encode()+b'\r\n\r\n')
                if method == 'GET':
                    writer.write(DEFAULT_ICON)
                await writer.drain()
                return
            cookie_header = values.get('cookie', '')
            if not cookie_header and re.fullmatch(r'jsessionid=[a-f0-9]{48}', matrix):
                cookie_header = 'JSESSIONID='+matrix.split('=', 1)[1]
            if method == 'GET' and route == '/ngi/axis/services/NGICommunity':
                writer.write(b'HTTP/1.0 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                await writer.drain()
                LOG.info('Community heartbeat completed')
                return
            if method != 'POST':
                raise ValueError('Expected HTTP POST')
            size = int(values['content-length'])
            if not 0 < size <= 65536:
                raise ValueError('Invalid request size')
            expectation = values.get('expect', '').lower()
            if expectation:
                if expectation != '100-continue':
                    raise ValueError('Unsupported HTTP expectation')
                writer.write(b'HTTP/1.1 100 Continue\r\n\r\n')
                await writer.drain()
            body = await asyncio.wait_for(reader.readexactly(size), 20)
            if body.lstrip().startswith(b'<'):
                self.record('SOAP '+route.partition('?')[0], body)
            game_service = {'/ngi/servlets/rankings': self.rankings,
                            '/ngi/servlets/xmlachievements': self.achievements}.get(route)
            if game_service is None and route not in {'/n-gage/axis/services/Community', '/ngi/axis/services/NGICommunity', '/ngi/axis/services/userprofile'}:
                writer.write(b'HTTP/1.0 501 Not Implemented\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                await writer.drain()
                return
            token, session = self.community_session(cookie_header, create=game_service is None)
            if game_service is not None:
                from arena.services.rankings.service import UnsupportedRanking
                try:
                    user = session.user if session else None
                    if user is None and not cookie_header:
                        user = self.local_game_user(body, writer.get_extra_info('peername')[0])
                    response = game_service.response(body, user)
                except (PermissionError, ValueError, ET.ParseError) as error:
                    status = (b'403 Forbidden' if isinstance(error, PermissionError) else
                              b'501 Not Implemented' if isinstance(error, UnsupportedRanking) else b'400 Bad Request')
                    writer.write(b'HTTP/1.0 '+status+b'\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                    await writer.drain()
                    LOG.info('Game request rejected for %s: %s', route, type(error).__name__)
                    return
            elif route == '/ngi/axis/services/userprofile':
                icon_url = default_icon_url(values.get('host'), bool(writer.get_extra_info('ssl_object')))
                response = self.profiles.response(body, session.user, default_icon_url=icon_url)
            else:
                response = self.soap_response(body, session, ngi=route == '/ngi/axis/services/NGICommunity')
            # The native Arena framework retains this cookie across game-room exits.
            cookie = f'Set-Cookie: JSESSIONID={token}; Path=/; HttpOnly\r\n'.encode() if token else b''
            writer.write(b'HTTP/1.0 200 OK\r\n' + cookie
                         + b'Content-Type: text/xml; charset=utf-8\r\nContent-Length: '
                         + str(len(response)).encode() + b'\r\n\r\n' + response)
            await writer.drain()
        except (ValueError, KeyError, UnicodeError, ET.ParseError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError, ConnectionError, TimeoutError) as error:
            LOG.info('Rejected malformed Community request (%s)', type(error).__name__)
        finally:
            self.writers.discard(writer)
            self.tasks.discard(asyncio.current_task())
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def xmpp(self, reader, writer):
        self.writers.add(writer)
        self.tasks.add(asyncio.current_task())
        parser = ET.XMLPullParser(events=('start', 'end'))
        depth = 0
        user = None
        connection = None
        domain = DOMAIN
        pending = 0
        previous = b''
        async def send(value):
            try:
                writer.write(value.encode())
                await asyncio.wait_for(writer.drain(), 10)
            except (OSError, asyncio.TimeoutError):
                writer.close()
                raise
        try:
            while data := await asyncio.wait_for(reader.read(16384), 30 if user is None else None):
                pending += len(data)
                if pending > 65536 or b'<!' in previous+data:
                    raise ValueError('Invalid XMPP stanza')
                previous = data[-1:]
                parser.feed(data)
                for event, node in parser.read_events():
                    if event == 'start':
                        depth += 1
                        if depth == 1:
                            root = node
                            if local(node.tag) != 'stream':
                                raise ValueError('Expected XMPP stream')
                            domain = node.get('to', DOMAIN)
                            if not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', domain):
                                raise ValueError('Invalid XMPP domain')
                            await send("<?xml version='1.0'?><stream:stream xmlns='jabber:client' xmlns:stream='http://etherx.jabber.org/streams' id='"+secrets.token_hex(8)+"' from='"+DOMAIN+"'>")
                        continue
                    if depth == 2:
                        self.record('XMPP', ET.tostring(node))
                        tag, identifier = local(node.tag), node.get('id', '')
                        if node.get('type') == 'error' or (tag == 'iq' and node.get('type') == 'result'):
                            root.remove(node)
                            node.clear()
                            pending = 0
                            depth -= 1
                            continue
                        if tag == 'iq':
                            query = next(iter(node), None)
                            if query is not None and query.tag == '{'+AUTH+'}query':
                                params = fields(query)
                                if node.get('type') == 'get':
                                    await send('<iq type="result" id='+quoteattr(identifier)+'><query xmlns="'+AUTH+'"><username>'+escape(params.get('username', ''))+'</username><password/><resource/></query></iq>')
                                else:
                                    if connection is not None:
                                        await self.messaging.disconnect(connection)
                                        connection = None
                                    self.snap_credentials.forget(writer)
                                    user = self.store.authenticate_snap(params.get('username', ''), params.get('password', ''))
                                    if user is None:
                                        await send('<iq type="error" id='+quoteattr(identifier)+'><error code="401">Unauthorized</error></iq>')
                                    else:
                                        name = self.store.name(user)
                                        self.snap_credentials.remember(writer, user, name, params['password'],
                                                                       writer.get_extra_info('peername')[0])
                                        connection = self.messaging.connect(user, domain, params.get('resource', 'segachat'), send)
                                        await send('<iq type="result" id='+quoteattr(identifier)+'/>')
                                        LOG.info('SNAP login completed for account %d', user)
                            elif user is None:
                                await send('<iq type="error" id='+quoteattr(identifier)+'><error code="401">Unauthorized</error></iq>')
                            elif query is not None and query.tag in ('{jabber:iq:roster}query', '{http://jabber.org/protocol/offline}query', '{http://jabber.org/protocol/disco#items}query'):
                                try:
                                    handler = self.messaging.roster if query.tag == '{jabber:iq:roster}query' else self.messaging.offline
                                    await handler(connection, node, query)
                                except (ValueError, LookupError, PermissionError) as error:
                                    await send('<iq type="error" id='+quoteattr(identifier)+'><error code="400">'+escape(str(error))+'</error></iq>')
                            else:
                                LOG.info('SNAP request %s to %s', identifier, node.get('to', ''))
                                await send('<iq type="error" id='+quoteattr(identifier)+'><error code="501">Not implemented</error></iq>')
                        elif tag in ('presence', 'message'):
                            if tag == 'message' and node.get('id') in ('segachat_retrieve_req', 'segachat_send_event'):
                                await send(self.snap_response(user, node))
                            else:
                                try:
                                    if connection is None:
                                        raise PermissionError('Login required')
                                    handler = self.messaging.presence if tag == 'presence' else self.messaging.message
                                    await handler(connection, node)
                                except (ValueError, LookupError, PermissionError) as error:
                                    await send('<'+tag+' type="error" id='+quoteattr(identifier)+' from='+quoteattr(node.get('to', domain))+'><error code="400">'+escape(str(error))+'</error></'+tag+'>')
                        root.remove(node)
                        node.clear()
                        pending = 0
                    depth -= 1
        except (ValueError, ET.ParseError, OSError, asyncio.TimeoutError) as error:
            LOG.info('SNAP connection closed: %s', error)
        finally:
            if connection is not None:
                await self.messaging.disconnect(connection)
            self.snap_credentials.forget(writer)
            self.writers.discard(writer)
            self.tasks.discard(asyncio.current_task())
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
