"""Game adapters registered by the service composition root."""


class GameRegistry:
    def __init__(self, games=()):
        self.games = {}
        for game in games:
            if game.game_class in self.games:
                raise ValueError('Duplicate game class: '+game.game_class)
            uid = getattr(game, 'app_uid', None)
            if uid is not None and self.for_uid(uid) is not None:
                raise ValueError('Duplicate game UID: '+str(uid))
            self.games[game.game_class] = game

    def for_uid(self, uid):
        return next((game for game in self.games.values() if getattr(game, 'app_uid', None) == uid), None)

    def retrieve(self, user, node):
        game = self.games.get(node.get('game_class_id'))
        if game is None or not hasattr(game, 'retrieve'):
            raise ValueError('Unknown game')
        return game.retrieve(user, node)

    def rankings(self, user, request):
        from arena.services.rankings.service import UnsupportedRanking
        game = self.games.get(request.game_class)
        if game is None or not hasattr(game, 'rankings'):
            raise UnsupportedRanking('Unsupported ranking game')
        return game.rankings(user, request)
