"""Unvoiced introductory conversation integrated with the native horse shop."""
import xml.etree.ElementTree as ET
from horse_trader_dialogue import DIALOG, ROLE
from upgrade_map import xml

PATH = 'Quests/GlueTravel/entry/horse_sales/'+DIALOG+'.xml'


def attach(resources):
    resources = dict(resources)
    root = ET.fromstring(resources[PATH])
    host = root.find('Skald/FaderDialog')
    ports = host.find('Ports')
    ET.SubElement(ports, 'Port', Name='getting_started_active', Type='bool', Direction='In')
    ET.SubElement(ports, 'Port', Name='getting_started_talked', Type='trigger', Direction='Out')
    choices = host.find(".//Decision[@Name='horses']/Sequences")
    if choices is None: raise ValueError('Horse shop decision missing')
    strings = ET.Element('Table')

    def text(parent, tag, key, value):
        key='ui_gm_getting_started_'+key
        ET.SubElement(parent,tag,StringName=key,Text=value)
        row=ET.SubElement(strings,'Row')
        for cell in (key,value,value):ET.SubElement(row,'Cell').text=cell

    def topic(name,prompt,henry,zora,condition=None):
        seq=ET.Element('Sequence',Name=name,EndType='GoTo',GoToDecision='horses',GrayOutIfSequencesUsed='Never')
        if condition:seq.set('EntryCondition',condition)
        text(seq,'UiPrompt',name+'_prompt',prompt)
        elements=ET.SubElement(seq,'Elements')
        for role,key,line in (('HENRY','henry',henry),(ROLE,'zora',zora)):
            text(ET.SubElement(elements,'Response',Role=role),'Text',name+'_'+key,line)
        return seq

    intro=topic('getting_started_intro','I am looking for a horse.',
        'I have gathered my supplies. Now I could use a horse for the road.',
        'Then you have come to the right place. I am Zora. My horses are in the paddock. Choose one that suits you, and we can settle the price. If you have a horse already, we can arrange a trade.',
        "Port('getting_started_active')")
    ET.SubElement(ET.SubElement(intro,'Triggers'),'Port',Name='getting_started_talked')
    advice=topic('horse_advice','What should I look for in a horse?',
        'What matters most when choosing a horse?',
        'That depends on the work. For long journeys, look at stamina. For carrying supplies, look at capacity. And if you expect trouble, you will want courage as well as speed.')
    choices.insert(0,intro);choices.insert(1,advice)
    resources[PATH]=xml(root)
    return resources,xml(strings)
