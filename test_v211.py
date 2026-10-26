from pathlib import Path
from PIL import Image
from server.candidates.llm_extractor import _exact_in_source
from server.api.routes import _merge_candidate_sources, _candidate_decision

assert _exact_in_source('GSR 18V-60','Bosch GSR 18V-60 - Perceuse-visseuse sans fil 18V','')
assert not _exact_in_source('GSR 18V-61','Bosch GSR 18V-60 - Perceuse-visseuse sans fil 18V','')
vision={'marque':'Nike','objet':'chaussure de sport'}
local=[{'id':'nike-p-6000','marque':'Nike','objet':'chaussure de sport','modele':'P-6000','source':'catalogue_local','score':0.38,'similarite_image':0.999,'raisons':['forte concordance visuelle']}]
web=[{'id':'web:p6000','marque':'Nike','objet':'chaussure de sport','modele':'P-6000','source':'web','score':0.86,'similarite_image_web':0.833,'raisons':['image + titre modèle concordants'],'urls':['https://www.nike.com/fr/t/x','https://www.snipes.com/fr/x'],'titres':['Nike P-6000 argent','Nike P-6000'],'domaines':['nike.com','snipes.com'],'preuves_titre_modele':2,'preuves_llm':2,'preuves_llm_certaines':2}]
other=[{'id':'web:airmax270','marque':'Nike','objet':'chaussure de sport','modele':'Air Max 270','source':'web','score':0.25,'raisons':['preuve textuelle avec marque'],'urls':['https://www.kaufland.fr/x'],'titres':['Nike Air Max 270 Sportschuhe Herren Trainingsschuhe'],'domaines':['kaufland.fr']}]
merged=_merge_candidate_sources(local,web,vision)
assert merged[0]['modele']=='P-6000', merged
assert sum(1 for x in merged if x['modele']=='P-6000')==1
assert all(x['modele']!='P-6000' or x['score']>=0.9 for x in merged)
merged2=_merge_candidate_sources(local,other,vision)
assert merged2[0]['modele']=='P-6000', merged2
print('OK V2.11 text extraction guards + candidate fusion')
