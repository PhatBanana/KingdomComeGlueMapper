"""Import book illustration textures under namespaced dynamic UI names."""
from campaign_dependencies import ImportPlan


class DocumentImageAdapter:
    def __init__(self, source, reader, namespace):
        self.source, self.reader, self.namespace = source, reader, namespace
        self.data = {}

    def plan(self, identity):
        if '/' in identity or '\\' in identity or '..' in identity:
            raise ValueError('Invalid document illustration identity')
        path = 'Libs/UI/Textures/Dynamic/'+identity+'.dds'
        record = self.reader(self.source, {'image':('GameData.pak',path)})['image']
        self.data[identity] = record['data']
        return ImportPlan(source=dict(path=path,provenance=record['candidates']))

    def convert(self, identity, plan, registered):
        name = self.namespace+'_'+identity
        return name, {'Libs/UI/Textures/Dynamic/'+name+'.dds':self.data[identity]}, dict(source=plan.source)
