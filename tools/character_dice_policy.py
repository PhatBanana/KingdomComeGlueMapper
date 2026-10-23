"""Private native opponent variant preserving the source no-money exit policy."""
import copy
import re
import uuid
import xml.etree.ElementTree as E

from character_station_work import unquote

CONDITION = 'return entity.inventory:GetMoney() >= SocialClass.GetEntitySocialClassData(entity).diceMinimumBet'


def minimum_bet(source_tree, social_class):
    gate = source_tree.find('Root/Behavior/LuaGate')
    if gate is None or unquote(gate.get('code', '')) != CONDITION:
        raise ValueError('Source gambler eligibility changed')
    for branch,target,behavior in [('Then','diceTable','diceOpponent'),('Else','leaningSpot','use')]:
        node=gate.find(branch+'/CallBehavior')
        if node is None or unquote(node.get('Target','')) != target or unquote(node.get('BehaviorName','')) != behavior:
            raise ValueError('Source gambler branches changed')
    code=re.sub(r'--[^\r\n]*','',social_class)
    block=re.search(r'SocialClass\.defaultValues\s*=\s*\{([^}]+)\}',code,re.S)
    value=None if block is None else re.search(r'\bdiceMinimumBet\s*=\s*(\d+)\s*,',block[1])
    if value is None or len(re.findall(r'\bdiceMinimumBet\b',code)) != 1:
        raise ValueError('Unsupported per-class or dynamic source dice minimum')
    return int(value[1])


def opponent(source_tree, social_class, native_program, native_template):
    minimum=minimum_bet(source_tree,social_class)
    tree=copy.deepcopy(native_program.find("BehaviorTree[@name='use_opponent']"))
    if tree is None:raise ValueError('Missing native dice opponent')
    root=tree.find('Root')
    sequence=root.find('Behavior/Decision/Exec/FuseBox/Child/Sequence')
    if sequence is None or [n.tag for n in list(sequence)[:4]] != ['NumericalOperation','Expression','Function_dice_checkMoney','IfCondition']:
        raise ValueError('Native dice money policy changed')
    amount,multiply,check,mint=list(sequence)[:4]
    if (amount.get('In1VariableName') != "data:script_param['dice_gameLevelBetSize_beggar'].value"
            or amount.get('OutVariableName') != '$amountToCheck' or multiply.get('expressions') != '$amountToCheck *= 10'
            or check.get('amountToCheck') != '$amountToCheck' or check.get('npcHasEnough') != '$hasEnoughMoney'):
        raise ValueError('Native dice money units changed')
    creates=list(root.iter('CreateItem'))
    if len(creates)!=1 or mint.find('Sequence/CreateItem') is not creates[0] or creates[0].get('Target')!='$this.id':
        raise ValueError('Native dice arriving grants changed')
    # Retain native insufficient-money cleanup/decision branch. Remove both the
    # currency grant and its forced true assignment, not merely CreateItem.
    for node in (amount,multiply,mint):sequence.remove(node)
    sequence.insert(0,E.Element('Expression',expressions='$amountToCheck = '+str(minimum*10)))
    for tag in ('EditorData','ForestContainer'):
        for node in tree.findall(tag):tree.remove(node)
    template=copy.deepcopy(native_template)
    identity=str(uuid.uuid5(uuid.NAMESPACE_URL,'kingdomcomegluemapper/source-dice-policy/v1/'+str(minimum)))
    template.set('DatabaseId',identity);template.set('Name','gm_source_dice_'+str(minimum))
    behavior=template.find("BehaviorTemplates/SmartBehaviorTemplate[@Name='use_opponent']")
    if behavior is None or behavior.get('InitialState')!='Disabled':raise ValueError('Native dice activation contract changed')
    # Native scheduled opponents use BehaviorOverride=true with this disabled
    # default. Keep the same scoped acquisition contract, not a global enable.
    location=behavior.find('TreeLocation')
    location.set('FileName','gluemapper/source_dice_'+str(minimum)+'.xml')
    return template,tree,dict(minimum_groschen=minimum,mints_money=False,activation='Disabled')


def conditional_leaning(tree, minimum, native_call):
    """Retain the authored left/right-only fallback without an idle timer.

    Source so_leanSpot sets canChangeLean=false when back leaning is forbidden;
    its initial equally likely left/right selection remains persistent.
    """
    if native_call.get('BehaviorName') != "'use'" or native_call.get('ignoreDropUnloading') != 'false':
        raise ValueError('Native smart-object call contract changed')
    result=copy.deepcopy(tree)
    root=result.find('Root');init=root.find('OnInit/Sequence');variables=result.find('Variables')
    if init is None or variables is None:raise ValueError('Native dice initialization missing')
    search=init.find('GraphSearch')
    if search is None or len(search)!=1 or search[0].tag!='LinkTagFilter':raise ValueError('Native dice graph query changed')
    for side in ('Left','Right'):
        E.SubElement(variables,'Variable',name='gmLean'+side,type='_wuid',values='',isPersistent='0',form='single')
        query=copy.deepcopy(search)
        query[0].set('tag',"'gm_sourceLean"+side+"'");query[0].set('Child','$gmLean'+side)
        init.append(query)
    E.SubElement(variables,'Variable',name='gmLeanSide',type='_int',values='0',isPersistent='1',form='single')
    choose=E.SubElement(init,'IfCondition',failOnCondition='false',condition='$gmLeanSide == 0')
    random=E.SubElement(choose,'RandomGate',opensWithChance='0.500000',saveVersion='2')
    for branch,value in [('Then','1'),('Else','2')]:
        E.SubElement(E.SubElement(random,branch,canSkip='1'),'Expression',expressions='$gmLeanSide = '+value)
    body=root.find('Behavior')
    if len(body)!=1 or body[0].tag!='Decision':raise ValueError('Native dice body changed')
    original=body[0];body.remove(original)
    gate=E.SubElement(body,'LuaGate',code='return entity.inventory:GetMoney() >= '+str(minimum),saveVersion='2')
    E.SubElement(gate,'Then',canSkip='1').append(original)
    fallback=E.SubElement(E.SubElement(gate,'Else',canSkip='1'),'EntityContextElement',
                           context='activity_disableSchedulerLooping',enabled='true')
    select=E.SubElement(fallback,'IfElseCondition',condition='$gmLeanSide == 1',failOnCondition='false',saveVersion='2')
    for branch,side in [('Then','Left'),('Else','Right')]:
        call=copy.deepcopy(native_call);call.attrib.pop('nodeLabel',None);call.set('Target','$gmLean'+side)
        E.SubElement(select,branch,canSkip='1').append(call)
    return result


def validate_leaning(source_tree):
    """Accept only the authored persistent left/right selection contract."""
    tree=copy.deepcopy(source_tree)
    if tree is None:raise ValueError('Missing source leaning behavior')
    for node in tree.iter():
        for key,value in list(node.attrib.items()):node.set(key,unquote(value))
    var=tree.find("Variables/Variable[@name='t_currentLean']")
    sequence=tree.find('Root/OnInit/Sequence')
    if var is None or var.get('isPersistent')!='1' or sequence is None:
        raise ValueError('Source lean persistence changed')
    back=sequence.find("IfElseCondition[@condition='$allowLeanBack']/Else/Expression")
    random=sequence.find("IfCondition[@condition=\"$t_currentLean == ''\"]/RandomItem")
    options={(p.get('condition'),n.get('argument')) for p in sequence.findall('IfCondition') for n in p.findall('VarOperation')
             if n.get('operation')=='PushBack' and n.get('varName')=='nextAllowedLeans'}
    if (back is None or back.get('expressions')!='$canChangeLean = false'
            or options!={('$t_allowLeanLeft','leaningLeft'),('$t_allowLeanRight','leaningRight')}
            or random is None or random.get('Array')!='nextAllowedLeans'
            or random.get('Result')!='t_currentLean' or random.get('Clamp')!='-1'):
        raise ValueError('Source left/right random leaning contract changed')
    body=tree.find('Root/Behavior/IncludeTree')
    if body is None or body.get('File')!='final/so_templates.xml' or body.get('Name')!='objectNewHelpers':
        raise ValueError('Source leaning lifecycle changed')


def lean_program(opponent_tree, minimum, native_call):
    """Independent lean host: no dice resource, readiness or cup ownership."""
    tree=conditional_leaning(opponent_tree,minimum,native_call)
    tree.set('name','use')
    variables=tree.find('Variables')
    for node in list(variables):
        if not node.get('name','').startswith('gmLean'):variables.remove(node)
    init=tree.find('Root/OnInit/Sequence')
    for node in list(init):
        if node.tag=='GraphSearch' and node[0].get('tag','').startswith("'gm_sourceLean"):continue
        if node.tag=='IfCondition' and node.get('condition')=='$gmLeanSide == 0':continue
        init.remove(node)
    body=tree.find('Root/Behavior');fallback=body.find('LuaGate/Else/EntityContextElement')
    body.clear();body.append(fallback)
    return tree
