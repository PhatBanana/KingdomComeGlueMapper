"""Native region/layer inheritance shared by clothing conversion and repair."""


def region_layers(node, parents):
    """Resolve both rigid and simulated elements; neither is a different slot.

    An absent layer remains None if no ancestor declares it. Never infer a
    numeric layer from the KCD1 mesh name or from a neighbouring body region.
    """
    chain = []
    while node is not None:
        chain.append(node)
        node = parents.get(node)
    result = {}
    for ancestor in reversed(chain):
        for element in ancestor.findall('Elements/*'):
            if element.tag not in ('SkinElement', 'VClothElement'):
                continue
            region = element.get('EquipmentPart')
            if not region:
                continue
            if element.get('BodyLayerId') is not None:
                result[region] = element.get('BodyLayerId')
            else:
                result.setdefault(region, None)
    return result


def project_regions(regions, contract, primary='torso'):
    """Keep complete source geometry in the regions authored by the native role."""
    if primary not in contract:
        raise ValueError('Native role has no primary region: ' + primary)
    return [region if region in contract else primary for region in regions]
