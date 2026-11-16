"""Bounded XML parsing and exact field paths from the KIPRIS Plus portal specification."""
from xml.etree import ElementTree as ET

MAX_RESPONSE = 2 * 1024 * 1024


class BoundedTree(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.depth = self.nodes = self.chars = 0

    def doctype(self, *args):
        raise ValueError('xml_dtd_forbidden')

    def start(self, tag, attrs):
        self.depth += 1
        self.nodes += 1
        if self.depth > 64 or self.nodes > 30000:
            raise ValueError('xml_structure_limit')
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)

    def data(self, data):
        self.chars += len(data)
        if self.chars > 1000000:
            raise ValueError('xml_text_limit')
        return super().data(data)


def parse(data):
    root = ET.fromstring(data, parser=ET.XMLParser(target=BoundedTree()))
    if root.tag != 'response':
        raise ValueError('unexpected_xml_envelope')
    return root


def text(node, path):
    element = node.find(path)
    return ''.join(element.itertext()).strip() if element is not None else None


def fields(node, names):
    return {name: text(node, name) for name in names}
