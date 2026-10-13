"""Import referenced KCD1 key items with their original GUIDs and text."""
import xml.etree.ElementTree as ET
from campaign_dependency_adapters import ItemAdapter, ItemTextAdapter, SourceTables
from campaign_dependencies import DependencyImporter
from campaign_sources import RetailSourceReader
from region_travel_dialogue import merge_localization
from upgrade_map import xml


class SourceKeyAdapter(ItemAdapter):
    def plan(self,identity):
        if not self.tables.row('item/item','item_id',identity,optional=True):
            # A shipped door refers to an absent item. Materialize its GUID
            # using the ordinary source door-key presentation and native type.
            key_ids={r['item_id'] for r in self.tables.get('item/key')['rows']}
            generic=next(r['item_id'] for r in self.tables.get('item/player_item')['rows']
                         if r['item_id'] in key_ids and r.get('ui_name')=='ui_nm_keyname_doors')
            plan=super().plan(generic)
            plan.source['recreated_missing_source_key']=identity
            return plan
        return super().plan(identity)

    def convert(self,identity,plan,registered):
        if plan.source['category'] not in ('key','misc'):
            raise ValueError('Unsupported source door key item class: '+identity)
        _,files,evidence=super().convert(identity,plan,registered)
        for name,blob in list(files.items()):
            root=ET.fromstring(blob)
            row=root.find('ItemClasses')[0]
            row.tag='MiscItem';row.set('Id',identity)
            row.set('Type','4');row.attrib.pop('SubType',None)
            row.set('IconId','key_general');row.set('PickpocketInPouch','true')
            files[name]=xml(root)
        evidence['target_id']=identity
        return identity,files,evidence


def build(source,keys,assets,namespace='worlddoors'):
    with RetailSourceReader(source) as reader:
        importer=DependencyImporter({'items':SourceKeyAdapter(SourceTables(source,reader),namespace),
                                     'assets':assets,'strings':ItemTextAdapter(source,namespace,'English')})
        for key in sorted(keys):
            if importer.ensure('items',key)!=key:
                failures=[(r['identity'],r.get('error')) for r in importer.report()['jobs'] if r['status']=='conversion_failed']
                raise ValueError('Door key dependency conversion failed: '+str(failures))
    files={};strings=b'<Table></Table>'
    for name,blob in importer.files.items():
        if name.startswith('localization/'):
            strings=merge_localization(strings,blob)
        else:files[name]=blob
    recovered=[r['identity'] for r in importer.report()['jobs']
               if r.get('source',{}).get('recreated_missing_source_key')]
    return files,strings,recovered
