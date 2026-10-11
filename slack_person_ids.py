"""Confirmed demo identities; match legacy IDs, never ambiguous names."""
PERSON_ID_MAP = {
    'PERSON-00001': 'U0C22C8M742',
    'PERSON-00002': 'U0C20G9MRML',
    'PERSON-00003': 'U0C6WSR5275',
    'PERSON-00004': 'U0C38J2MUF4',
    'PERSON-00013': 'U0C33QKTX09',
    'PERSON-00017': 'U0C1M3Q1PRV',
    'PERSON-00024': 'U0C4KAAFA1Z',
    **{'PERSON-00005': 'U00005', 'PERSON-00006': 'U00006', 'PERSON-00007': 'U00007', 'PERSON-00008': 'U00008', 'PERSON-00009': 'U00009', 'PERSON-00010': 'U00010', 'PERSON-00011': 'U00011', 'PERSON-00012': 'U00012', 'PERSON-00014': 'U00014', 'PERSON-00015': 'U00015', 'PERSON-00016': 'U00016', 'PERSON-00018': 'U00018', 'PERSON-00019': 'U00019', 'PERSON-00020': 'U00020', 'PERSON-00021': 'U00021', 'PERSON-00022': 'U00022', 'PERSON-00023': 'U00023', 'PERSON-00025': 'U00025', 'PERSON-00026': 'U00026', 'PERSON-00027': 'U00027', 'PERSON-00028': 'U00028', 'PERSON-00029': 'U00029', 'PERSON-00030': 'U00030', 'PERSON-00031': 'U00031', 'PERSON-00032': 'U00032', 'PERSON-00033': 'U00033', 'PERSON-00034': 'U00034', 'PERSON-00035': 'U00035', 'PERSON-00036': 'U00036', 'PERSON-00037': 'U00037', 'PERSON-00038': 'U00038', 'PERSON-00039': 'U00039', 'PERSON-00040': 'U00040', 'PERSON-00041': 'U00041', 'PERSON-00042': 'U00042', 'PERSON-00043': 'U00043', 'PERSON-00044': 'U00044', 'PERSON-00045': 'U00045', 'PERSON-00046': 'U00046', 'PERSON-00047': 'U00047', 'PERSON-00048': 'U00048', 'PERSON-00049': 'U00049', 'PERSON-00050': 'U00050'},
}


def normalize_person_ids(value):
    """Return a copy with exact ID values and tensor lookup keys normalized."""
    if isinstance(value, str):
        return PERSON_ID_MAP.get(value, value)
    if isinstance(value, list):
        return [normalize_person_ids(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            new_key = PERSON_ID_MAP.get(key, key)
            if new_key in result:
                raise ValueError('Person ID lookup key collision: ' + new_key)
            result[new_key] = normalize_person_ids(item)
        return result
    return value


def normalize_graph(graph):
    result = normalize_person_ids(graph)
    ids = [node['id'] for node in result['nodes']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate node ID after Slack normalization')
    return result
