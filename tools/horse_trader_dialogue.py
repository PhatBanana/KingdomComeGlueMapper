"""Native horse purchase dialogue and locally scoped purchase graph dependencies."""
import copy
import xml.etree.ElementTree as ET

from upgrade_map import read, xml

ROLE = 'GM_NEUHOF_HORSE_TRADER'
DIALOG = 'gm_neuhof_horse_sales'
BASE = 'Quests/Final/Barbora/utils/'


def helpers(archive, directory):
    """Import only the six native modules used by a cash horse purchase.

    Resolve their library names locally, without instantiating the entire
    Trosky campaign or relying on a previous Trosky session's utility graph.
    """
    sources = ('horsebuying_utils/horseinstance', 'horsebuying_utils/horsebuying_payment',
               'horsebuying_utils/replaceplayerhorse_disposeoldifexists',
               'money/hasmoney', 'money/converttogroshen', 'general/minfloat')
    names = {p.rsplit('/', 1)[-1] for p in sources}
    result = {}
    for path in sources:
        root = ET.fromstring(read(archive, BASE + path + '.xml'))
        module = root.find('Skald/Module')
        if module is None: raise ValueError('Expected native horse purchase module: ' + path)
        for node in module.findall('Nodes/*'):
            if node.tag in names: node.set('Namespace', '')
        result[directory + '/' + module.get('Name') + '.xml'] = xml(root)
    return result


def dialogue(horses, seller):
    root = ET.Element('Database', Name='brambora')
    host = ET.SubElement(ET.SubElement(root, 'Skald'), 'FaderDialog', Name=DIALOG)
    ports = ET.SubElement(host, 'Ports')
    body = ET.SubElement(host, 'Dialogue', TechnicalStatus='Enabled', Initiator='Player',
                         NonSpeakerRoles=ROLE, AllowGreeting='false', AllowFarewell='false')
    selected = ET.SubElement(body, 'SelectedSouls')
    ET.SubElement(selected, 'SelectedSoul', Role='HENRY', Voice='tomMcKay', Type='Wave', Language='ENG')
    ET.SubElement(selected, 'SelectedSoul', Role=ROLE, Soul=seller, Type='Wave', Language='ENG')
    trace = ("local ok,result=pcall(function() local id=player.player:GetHorseId(); "
             "local h=id and System.GetEntity(id); local p=h and h:GetWorldPos(); "
             "return 'horse='..tostring(h and h:GetName())..' id='..tostring(id)..' position='.."
             "tostring(p and p.x)..','..tostring(p and p.y)..','..tostring(p and p.z) end); "
             "System.LogAlways('GLUE_HORSE_SALE event=talk query_ok='..tostring(ok)..' '..tostring(result))")
    entry = ET.SubElement(body, 'Decision', Name='conversation_entry', Priority='General', Autoselect='true')
    begin = ET.SubElement(ET.SubElement(entry, 'Sequences'), 'Sequence', Name='begin',
                          EndType='Decision', ExitScript=trace)
    ET.SubElement(ET.SubElement(begin, 'Elements'), 'Response', Role='HENRY')
    choices = ET.SubElement(ET.SubElement(begin, 'Decision', Name='horses', Priority='General',
                                         Autoselect='false'), 'Sequences')
    strings = ET.Element('Table')

    def prompt(node, key, text):
        key = 'ui_gm_horse_' + key
        ET.SubElement(node, 'UiPrompt', StringName=key, Text=text)
        row = ET.SubElement(strings, 'Row')
        for value in (key, text, text): ET.SubElement(row, 'Cell').text = value

    for index, horse in enumerate(horses):
        key = f'h{index:02}'
        for name, typ, direction in ((key+'_available', 'bool', 'In'), (key+'_money', 'bool', 'In'),
                ('Payment_buy_'+key, 'float', 'In'), ('Payment_refund_'+key, 'float', 'In'),
                (key+'_buy', 'trigger', 'Out')):
            ET.SubElement(ports, 'Port', Name=name, Type=typ, Direction=direction)
        choice = ET.SubElement(choices, 'Sequence', Name='select_'+key, EndType='Decision',
                              EntryCondition=f"Port('{key}_available')", GrayOutIfSequencesUsed='Never')
        prompt(choice, key, horse['display_name'])
        ET.SubElement(ET.SubElement(choice, 'Elements'), 'Response', Role='HENRY')
        options = ET.SubElement(ET.SubElement(choice, 'Decision', Name='confirm_'+key,
                                             Priority='General', Autoselect='false'), 'Sequences')
        # Payment UI uses Payment_<sequence name>, as the native horse trader does.
        # The native exchange value includes the existing horse's trade-in value.
        for refund in (False, True):
            action = ('refund_' if refund else 'buy_') + key
            condition = f"Port('{key}_available') AND " + (
                f"!Port('Payment_buy_{key}')" if refund else
                f"Port('{key}_money') AND Port('Payment_buy_{key}')")
            amount = f"Ports['Payment_{action}'] * " + ('-10' if refund else '10')
            script = (f"Shops.DoMoneyTransaction(dc['{ROLE}'].id, {amount}, 0); "
                      f"Game.ShowItemsTransfer(ItemUtils.itemIDs.money, -({amount})); "
                      f"System.LogAlways('GLUE_HORSE_SALE event=payment horse={horse['name']} decigroschen=' .. tostring({amount}))")
            buy = ET.SubElement(options, 'Sequence', Name=action, EndType='EndDialogue', Type='Payment',
                                EntryCondition=condition, ExitScript=script, GrayOutIfSequencesUsed='Never')
            prompt(buy, action, '(Trade in your horse and receive the difference)' if refund else '(Buy horse / trade in current horse)')
            ET.SubElement(ET.SubElement(buy, 'Triggers'), 'Port', Name=key+'_buy')
            ET.SubElement(ET.SubElement(buy, 'Elements'), 'Response', Role='HENRY')
        cancel = ET.SubElement(options, 'Sequence', Name='cancel_'+key, EndType='GoTo', GoToDecision='horses')
        prompt(cancel, 'cancel_'+key, '(Back)')
        ET.SubElement(ET.SubElement(cancel, 'Elements'), 'Response', Role='HENRY')
    leave = ET.SubElement(choices, 'Sequence', Name='leave', EndType='EndDialogue')
    ET.SubElement(leave, 'UiPrompt', StringName='ui_end_topic', Text='(End dialog)')
    ET.SubElement(ET.SubElement(leave, 'Elements'), 'Response', Role='HENRY')
    return xml(root), xml(strings)


def attach(resources, entry_path, horses, seller_guid, scripts, seller='neu_zdena'):
    """Put the purchase modules and dialogue under the destination Level.

    Its LevelHolder binds area and stash; the helper's player/playerHorse
    aliases retain the game's special shared-soul identities.
    """
    result = dict(resources)
    directory = entry_path.rsplit('/', 1)[0] + '/horse_sales'
    result.update(helpers(scripts, directory))
    root = ET.fromstring(result[entry_path]); level = root.find('Skald/Level')
    definitions = level.find('Definitions')
    if definitions is None: definitions = ET.SubElement(level, 'Definitions')
    for filename in ('horseinstance', 'horsebuying_payment', 'replaceplayerhorse_disposeoldifexists',
                     'hasmoney', 'converttogroshen', 'minfloat', DIALOG):
        ET.SubElement(definitions, 'Definition', File='horse_sales/'+filename+'.xml')
    assets = level.find('Assets')
    if assets is None: assets = ET.SubElement(level, 'Assets')
    native = ET.fromstring(read(scripts, 'Quests/Final/Barbora.xml'))
    for alias in ('player', 'player_any', 'playerHorse'):
        if assets.find(f"*[@Name='{alias}']") is None:
            assets.append(copy.deepcopy(native.find(f".//Assets/SoulAsset[@Name='{alias}']")))
    ET.SubElement(assets, 'SoulAsset', Name='horse_seller', SharedSoulGuids=seller_guid)
    ET.SubElement(assets, 'StashAsset', Name='horse_shop_stash')
    ET.SubElement(assets, 'TriggerAreaAsset', Name='horse_shop_area')
    nodes = level.find('Nodes')
    dialog = ET.SubElement(nodes, DIALOG, Name=DIALOG)
    for index, horse in enumerate(horses):
        key = f'h{index:02}'
        ET.SubElement(assets, 'SoulAsset', Name=key, SharedSoulGuids=horse['soul']['soul_id'])
        instance = ET.SubElement(nodes, 'horseinstance', Name=key+'_sale')
        for port, alias in (('horse', key), ('seller', 'horse_seller'), ('shopstash', 'horse_shop_stash'),
                            ('areacheck', 'horse_shop_area')):
            ET.SubElement(instance, 'Asset', Name=port, Alias=alias)
        ET.SubElement(instance, 'Edge', From=DIALOG+'.'+key+'_buy', To='buyviacash')
        for src, dest in (('isavailabletobuy', key+'_available'), ('moneyavailable', key+'_money'),
                          ('payment_player', 'Payment_buy_'+key), ('payment_stable', 'Payment_refund_'+key)):
            ET.SubElement(dialog, 'Edge', From=key+'_sale.'+src, To=dest)
    result[entry_path] = xml(root)
    result[directory+'/'+DIALOG+'.xml'], strings = dialogue(horses, seller)
    return result, strings
