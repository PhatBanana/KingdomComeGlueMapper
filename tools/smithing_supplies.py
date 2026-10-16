"""Native recipe documents and ingredients for ten crafts of each test recipe."""
from collections import Counter
import xml.etree.ElementTree as ET
from upgrade_map import read

RECIPES = ('r_axebattle01', 'r_horseshoe', 'r_huntingSwordBasic', 'r_longswordcommon')


def supplies(tables, batches=10):
    items = list(ET.fromstring(read(tables,'Libs/Tables/item/item.xml')).find('ItemClasses'))
    byid = {e.get('Id'):e for e in items}
    recipes = {e.get('Id'):e for e in ET.fromstring(read(tables,'Libs/Tables/minigame/BlacksmithRecipes.xml')).iter('BlacksmithRecipe')}
    amounts = Counter(); books = []
    for key in RECIPES:
        recipe = recipes[key]
        if recipe.get('DlcId'):raise ValueError('Test recipe acquired DLC requirement')
        documents = [e for e in items if e.get('BlacksmithRecipeId')==key]
        if len(documents)!=1:raise ValueError('Missing or ambiguous recipe document '+key)
        book=documents[0];books.append(dict(name=book.get('Name'),id=book.get('Id'),amount=1,recipe=key))
        for ingredient in recipe.findall('Ingredients/BlacksmithRecipeIngredient'):
            amounts[ingredient.get('ItemClassId')] += int(ingredient.get('Amount'))*batches
    return books + [dict(name=byid[key].get('Name'),id=key,amount=amount) for key,amount in sorted(amounts.items())]


def extend_preset(payload, items):
    root=ET.fromstring(payload)
    preset=root.find("InventoryPresets/InventoryPreset[@Name='gm_debug_forest_supplies']")
    if preset is None:raise ValueError('Missing test chest preset')
    for item in items:
        existing=[e for e in preset if e.get('ItemClassId')==item['id']]
        if existing:raise ValueError('Smithing supplies already present')
        ET.SubElement(preset,'PresetItem',Name=item['name'],ItemClassId=item['id'],Amount=str(item['amount']),Health='1',Quality='1')
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)
