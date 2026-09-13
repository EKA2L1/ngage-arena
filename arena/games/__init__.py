"""Game adapters registered by the service composition root."""


class GameRegistry:
    def __init__(self, games=()):
        self.games = {}
        for game in games:
            if game.game_class in self.games:
                raise ValueError('Duplicate game class: '+game.game_class)
            self.games[game.game_class] = game

    def retrieve(self, user, node):
        game = self.games.get(node.get('game_class_id'))
        if game is None or not hasattr(game, 'retrieve'):
            raise ValueError('Unknown game')
        return game.retrieve(user, node)

    def rankings(self, user, request):
        from arena.rankings import UnsupportedRanking
        game = self.games.get(request.game_class)
        if game is None or not hasattr(game, 'rankings'):
            raise UnsupportedRanking('Unsupported ranking game')
        return game.rankings(user, request)
