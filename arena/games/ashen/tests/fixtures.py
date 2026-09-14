import xml.etree.ElementTree as ET

def leaderboard(stat='game_total'):
    # Native Ashen's request asks for a seven-row, all-time leaderboard.
    node = ET.fromstring('<message to="retrieval@ngage-auth" id="segachat_retrieve_req" event_type="topn" game_class_id="42318" snap_name="forged"/>')
    request = ET.Element('itemlist')
    for key, value in dict(queryid='3dabc', board='HIGHSCORES', stat=stat, offset='0', limit='7',
                           periodicity='alltime', ordering='natural', format='csv').items():
        ET.SubElement(request, 'item', name=key, value=value)
    ET.SubElement(ET.SubElement(node, 'retrieve'), 'request').text = ET.tostring(request, encoding='unicode')
    return node
