"""Explicit KCD1 -> KCD2 ambience substitutions, never cinematic audio banks.

These are native semantic substitutes, not claims of identical recordings.
Retired mixer parameters are omitted rather than driving unrelated global RTPCs.
"""

TRIGGERS = {
    'a_l_village_skalice': 'a_l_village_amb01',
    'a_l_village_talmberk_country': 'a_l_village_amb02',
    'a_l_village_talmberk': 'a_l_village_amb03',
    'a_l_village_kolbens': 'a_l_village_amb04',
    'a_l_rataje': 'a_l_busy_street01',
    'a_l_rataje_upper_castle': 'a_l_quiet_estate',
    'a_l_pub01': 'a_l_pub01_inside', 'a_l_pub02': 'a_l_pub02_outside',
    'a_l_watermill_clap': 'a_l_watermill_clack',
    'a_l_watermill_clap_small': 'a_l_watermill_clack_small',
    'a_o_windmill2': 'a_l_windmill1',
    'a_l_water_stream_dam1': 'a_l_water_dam01',
    'a_l_water_stream16': 'a_l_water_stream15',
    'a_l_water_stream18': 'a_l_water_stream17',
    'a_l_fire_medium1_in': 'a_l_fire1_in',
    'a_l_wind_inside01': 'a_l_wind_interior_01',
    'a_l_forest05q': 'a_l_forest05',
    'a_l_forest11': 'a_l_forest01', 'a_l_forest12': 'a_l_forest02',
    'a_l_forest14': 'a_l_forest04', 'a_l_forest16': 'a_l_forest06',
    'a_l_forest17': 'a_l_forest07', 'a_l_forest18': 'a_l_forest08',
    'a_l_forest19': 'a_l_forest09',
    'a_l_wind_forest01': 'a_l_forest_trosecko_ne',
    'a_l_wind_forest02': 'a_l_forest_trosecko_nw',
    'a_l_wind_outside01': 'a_l_meadow01', 'a_l_wind_outside02': 'a_l_meadow02',
    'a_l_wind_outside03': 'a_l_meadow03', 'a_l_wind_outside04': 'a_l_meadow04',
    'a_l_lake03': 'a_l_lake01', 'a_l_lake04': 'a_l_lake02',
    'a_l_cave_hynek': 'a_l_cave01', 'a_l_tunnel_by_rattay': 'a_l_cave02',
    'a_l_house2': 'a_l_house02', 'a_l_infirmarium': 'a_l_house01',
    'a_l_flies': 'a_l_flies_small', 'a_o_tree_creak1': 'a_o_tree_creak_01',
    'a_o_night_wood_rumble': 'a_o_tree_creak_02',
    'a_o_dog01': 'a_o_dogs', 'a_o_fish1': 'a_o_fish',
    'a_o_church_bell_rataje': 'a_o_bell_krat',
    'a_o_buteo_buteo': 'a_o_kane',
    'a_o_birds_woodpecker': 'a_o_brhlik_idle',
    'a_o_picus_viridis': 'a_o_brhlik_idle',
    'a_o_nightingale': 'a_o_lelek_idle',
    'a_o_birds_owl_eurasian_pygmy': 'a_o_lelek_idle',
    'a_o_birds_owl_little': 'a_o_lelek_idle',
    'a_o_birds_owl_tawny': 'a_o_lelek_idle',
    'a_o_birds_magpie': 'a_o_sojka_idle', 'a_o_birds_magpie1': 'a_o_sojka_idle',
    'a_o_birds_magpie2': 'a_o_sojka_idle', 'a_o_birds_scared1': 'a_o_spacek_scared',
    'a_o_birds_swallow1': 'a_o_spacek_idle',
    'a_o_birds_duck1': 'a_l_meadow_birds_1',
    'a_o_birds_lake1': 'a_l_meadow_birds_1', 'a_o_birds_lake2': 'a_l_meadow_birds_1',
    'a_o_collared_dove': 'a_l_dovecote',
    'a_o_birds_acrocephalus_paludicola': 'a_o_skrivan_polni',
    'a_o_birds_crex_crex': 'a_o_skrivan_polni',
    'a_o_hornet': 'a_l_garden_insects_loop',
}
for number in (1, 4, 7, 9, 10, 12, 15, 16, 17):
    TRIGGERS[f'a_o_birds_bird{number:02d}'] = 'a_o_spacek_idle'
TRIGGERS['a_o_bird13'] = 'a_o_spacek_idle'
for number in (1, 3, 5, 6, 7, 9):
    TRIGGERS[f'a_o_cricket{number:02d}'] = 'a_l_garden_insects_loop'

ENVIRONMENTS = {
    'indoor_hut1': 'indoor_shed1_small', 'indoor_hut2': 'indoor_shed2_medium',
    'indoor_hut3': 'indoor_shed3_large', 'indoor_hu1': 'indoor_shed1_small',
    'indoor_house1_2': 'indoor_house1', 'indoor_cave_entry': 'indoor_c_cave_entrance',
    'indoor_cave1': 'indoor_cave_01', 'indoor_cave2': 'indoor_c_cave',
    'indoor_cave3': 'indoor_c_cave', 'indoor_cave4': 'indoor_c_cave',
    'indoor_rat_church_stairs': 'indoor_church_01',
    'indoor_rat_church_nave': 'indoor_church_01',
    'indoor_rat_church_room': 'indoor_house1', 'indoor_church1_lod': 'indoor_church_01',
    'indoor_aus_church_nave': 'indoor_church_01',
    'indoor_aus_church_steeple': 'indoor_hall_01',
    'indoor_sas_monastery2': '1200_indoor_church',
    'indoor_sas_mon_aisle': '1200_indoor_corridor',
    'indoor_sas_mon_nave': '1200_indoor_church',
    'indoor_sas_room1': 'indoor_house1', 'indoor_sas_room2': 'indoor_house2',
    'indoor_sas_library': '1200_indoor_rooms_big',
    'indoor_sas_corridor': '1200_indoor_corridor',
    'indoor_sas_stairs': '1200_indoor_corridor',
    'indoor_sas_cellar': '1200_indoor_underground',
    'indoor_sas_gate': 'outdoor_gate_medium',
    'indoor_rat_burg_house': 'indoor_house2',
    'indoor_rat_burg_cellar': 'indoor_cave_01',
    'indoor_rat_cellar1': 'indoor_cave_01', 'indoor_rat_cellar2': 'indoor_cave_01',
    'indoor_rat_pirkstejn_tower1': 'indoor_hall_01',
    'indoor_rat_pirkstejn_tower2': 'indoor_hall_02',
    'indoor_tlm_corridor': '1200_indoor_corridor',
    'indoor_tlm_gate': 'outdoor_gate_medium', 'indoor_tlm_armory': 'indoor_house2',
    'indoor_tlm_yard': 'outdoor_yard1', 'indoor_windmill': 'indoor_barn1',
    'outdoor_sas_garden1': 'outdoor_yard1', 'outdoor_rat_yard': 'outdoor_yard2',
    'outside': 'outdoor_forced_overground', 'outdoor': 'outdoor_forced_overground',
}

# KCD2's native weather/biome/particle controls replace these old global mix
# inputs. Do not alias them to unrelated gameplay or alchemy RTPCs.
RETIRED = {'ATLEnvironment': {'fxwater', 'fx_water', 'fxwater2', 'fx_grass', 'fx_rock'},
           'ATLRtpc': {'fireplace_amount', 'ambient_morphing', 'wind_add', 'amb_sub', 's'},
           # KCD1's random village one-shots sit beside a village loop area. KCD2
           # has no one-shot equivalent, and loop-substituting them doubles the loop.
           'ATLTrigger': {'mus_enforced_stealth_music', 'a_o_village_oneshot'}}


def aliases():
    result = {('ATLTrigger', a): b for a,b in TRIGGERS.items()}
    result.update({('ATLEnvironment', a): b for a,b in ENVIRONMENTS.items()})
    result.update({('ATLRtpc', 'amb_fade-dist'): 'amb_fade_dist',
                   ('ATLRtpc', 'amb-fade_dist'): 'amb_fade_dist'})
    return result
