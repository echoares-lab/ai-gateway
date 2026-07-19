"""Sample handler classes with intentionally near-identical method bodies."""


class InvoiceHandler:
    def __init__(self, name):
        self.name = name

    def process(self, x):
        return x + 1

    def describe(self):
        return f"InvoiceHandler({self.name})"


class OrderHandler:
    def __init__(self, name):
        self.name = name

    def process(self, x):
        return x + 1

    def describe(self):
        return f"OrderHandler({self.name})"


class ShipmentHandler:
    def __init__(self, name):
        self.name = name

    def process(self, x):
        return x + 1

    def describe(self):
        return f"ShipmentHandler({self.name})"
