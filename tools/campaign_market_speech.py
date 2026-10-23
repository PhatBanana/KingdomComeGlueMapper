"""Use the shipped market-seller activity with isolated imported work speech."""
import copy
import hashlib
import xml.etree.ElementTree as E
import zipfile
import uuid
from pathlib import Path
from campaign_quest_graph import xml, identifier
from character_market_jobs import contract
from upgrade_map import read


def clone_market(target, metarole, namespace):
    identifier(namespace); identifier(metarole)
    template=contract(target)
    activity=template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='seller_market']")
    location=activity.find('TreeLocation')
    with zipfile.ZipFile(Path(target)/'Data/Scripts.pak') as z:
        original=read(z,'AI/'+location.get('FileName'))
        speech=read(z,'AI/speech/schedulermonolog.xml')
        consumer=E.fromstring(speech).find("BehaviorTree/Root/.//DoMonologue")
        if consumer is None or any(consumer.get(k)!=v for k,v in {
                'Metaroles':'$metarole','SoulId':'$this.id','SkipInLOD':'$skipInLod',
                'AnimationOverride':'$animationState'}.items()):
            raise ValueError('Native scheduled monologue ownership contract changed')
    root=E.fromstring(original)
    tree=root.find("BehaviorTree[@name='"+location.get('TreeName')+"']")
    result,receipt=retarget_market(tree,metarole)
    output=E.Element(root.tag,root.attrib); output.append(result)
    # Keep the original activity and template shape, replacing only its identity
    # and the private worker location. Other native activities remain native.
    old=template.get('DatabaseId')
    template.set('DatabaseId',str(uuid.uuid5(uuid.NAMESPACE_URL, 'gluemapper/work-speech/'+namespace)))
    template.set('Name',namespace)
    location.set('FileName',namespace+'.xml')
    table=E.Element('database',name='barbora'); E.SubElement(table,'SmartEntitys',version='1').append(template)
    return {'AI/'+namespace+'.xml':xml(output),
            'Libs/Tables/ai/smartEntity/SmartEntity__'+namespace+'.xml':xml(table)},dict(
                receipt,original_template=old,template=template.get('DatabaseId'),
                source_native_sha256=hashlib.sha256(original).hexdigest(),
                native_consumer_sha256=hashlib.sha256(speech).hexdigest())


def retarget_market(tree,metarole):
    identifier(metarole)
    result=copy.deepcopy(tree)
    program=result.find('Root')
    requests=program.findall('.//Function_speech_schedulerMonolog')
    if len(requests)!=1:raise ValueError('Native market speech dispatch changed')
    call=requests[0]
    if (call.get('metarole')!="'NPC_VYVOLAVANI_NA_TRHU'" or call.get('alias')!=''
            or call.get('animationApproach')!='$enum:animationApproach.dontPlayDialogAnimations'
            or call.get('skipInLod')!='true'):
        raise ValueError('Unsupported native market speech contract')
    ancestors={child:parent for parent in program.iter() for child in parent}
    chain=[]; node=call
    while node in ancestors:node=ancestors[node];chain.append(node)
    if not any(n.tag=='EntityContextCheck' and n.get('context')=='seller_disableMarketCries' for n in chain):
        raise ValueError('Missing native market silence guard')
    if not any(n.tag=='RandomGate' for n in chain):raise ValueError('Missing native market selection gate')
    call.set('metarole',"'"+metarole+"'")
    editor=result.find('EditorData')
    if editor is not None:result.remove(editor)
    return result,dict(policy='Existing native market service cadence and cancellation; source speech content and memberships',
        metarole=metarole,source_gesture_policy='Native activity retains pose; legacy dialog gestures are not replayed',
        runtime_verified=False)
