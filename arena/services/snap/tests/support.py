class Transport:
    def __init__(self):
        self.sent = []

    def sendto(self, wire, peer):
        self.sent.append((peer, wire))
