def local(tag):
    return tag.rsplit('}', 1)[-1]


def fields(element):
    return {local(child.tag): child.text or '' for child in element}
