"""Helpers to resolve drug names to English/Latin (MNN) for Wikimedia search.

Wikipedia/Commons indexes mostly English content, so we improve hit rate by
searching with multiple variants:
  1. Russian trade name
  2. Russian MNN (международное непатентованное наименование)
  3. Latin MNN (mnn_latin field — if present)

The list of MNN translit fallbacks below covers the most common Russian MNNs
that DO have Wikipedia/Commons photos.
"""
import re

# Curated translit / English form for popular Russian MNNs that have Wikipedia entries
MNN_TRANSLIT = {
    "ПАРАЦЕТАМОЛ": "Paracetamol",
    "АЦЕТИЛСАЛИЦИЛОВАЯ КИСЛОТА": "Aspirin",
    "ИБУПРОФЕН": "Ibuprofen",
    "МЕТАМИЗОЛ НАТРИЯ": "Metamizole",
    "ДИКЛОФЕНАК": "Diclofenac",
    "НАПРОКСЕН": "Naproxen",
    "НИМЕСУЛИД": "Nimesulide",
    "КЕТОПРОФЕН": "Ketoprofen",
    "КЕТОРОЛАК": "Ketorolac",
    "АМОКСИЦИЛЛИН": "Amoxicillin",
    "АЗИТРОМИЦИН": "Azithromycin",
    "ЦЕФТРИАКСОН": "Ceftriaxone",
    "ЦЕФОТАКСИМ": "Cefotaxime",
    "ЦЕФАЗОЛИН": "Cefazolin",
    "ЛЕВОФЛОКСАЦИН": "Levofloxacin",
    "ЦИПРОФЛОКСАЦИН": "Ciprofloxacin",
    "ОФЛОКСАЦИН": "Ofloxacin",
    "МЕТРОНИДАЗОЛ": "Metronidazole",
    "ЛИНЕЗОЛИД": "Linezolid",
    "ХЛОРАМФЕНИКОЛ": "Chloramphenicol",
    "ДОКСИЦИКЛИН": "Doxycycline",
    "ВАНКОМИЦИН": "Vancomycin",
    "ИМИПЕНЕМ": "Imipenem",
    "МЕРОПЕНЕМ": "Meropenem",
    "АЦИКЛОВИР": "Aciclovir",
    "ВАЛАЦИКЛОВИР": "Valaciclovir",
    "ФАВИПИРАВИР": "Favipiravir",
    "ОСЕЛТАМИВИР": "Oseltamivir",
    "ИВЕРМЕКТИН": "Ivermectin",
    "КЛОТРИМАЗОЛ": "Clotrimazole",
    "ФЛУКОНАЗОЛ": "Fluconazole",
    "ИТРАКОНАЗОЛ": "Itraconazole",
    "ЭТАНОЛ": "Ethanol",
    "ХЛОРГЕКСИДИН": "Chlorhexidine",
    "ЙОД": "Iodine",
    "ПРОКАИН": "Procaine",
    "ЛИДОКАИН": "Lidocaine",
    "БУПИВАКАИН": "Bupivacaine",
    "РОПИВАКАИН": "Ropivacaine",
    "ДЕКСТРОЗА": "Glucose",
    "НАТРИЯ ХЛОРИД": "Sodium chloride",
    "ГЛИЦЕРОЛ": "Glycerol",
    "АСКОРБИНОВАЯ КИСЛОТА": "Ascorbic acid",
    "САЛИЦИЛОВАЯ КИСЛОТА": "Salicylic acid",
    "ВОДА ДЛЯ ИНЪЕКЦИЙ": "Water for injection",
    "ПИРАЦЕТАМ": "Piracetam",
    "ФУРОСЕМИД": "Furosemide",
    "ГИДРОХЛОРОТИАЗИД": "Hydrochlorothiazide",
    "СПИРОНОЛАКТОН": "Spironolactone",
    "БИСОПРОЛОЛ": "Bisoprolol",
    "МЕТОПРОЛОЛ": "Metoprolol",
    "АТЕНОЛОЛ": "Atenolol",
    "АМЛОДИПИН": "Amlodipine",
    "ВЕРАПАМИЛ": "Verapamil",
    "ЭНАЛАПРИЛ": "Enalapril",
    "ЛИЗИНОПРИЛ": "Lisinopril",
    "ПЕРИНДОПРИЛ": "Perindopril",
    "ЛОЗАРТАН": "Losartan",
    "ВАЛЬСАРТАН": "Valsartan",
    "ТЕЛМИСАРТАН": "Telmisartan",
    "ВАРФАРИН": "Warfarin",
    "АТОРВАСТАТИН": "Atorvastatin",
    "СИМВАСТАТИН": "Simvastatin",
    "РОЗУВАСТАТИН": "Rosuvastatin",
    "МЕТФОРМИН": "Metformin",
    "ГЛИБЕНКЛАМИД": "Glibenclamide",
    "ГЛИКЛАЗИД": "Gliclazide",
    "ИНСУЛИН": "Insulin",
    "ОМЕПРАЗОЛ": "Omeprazole",
    "ПАНТОПРАЗОЛ": "Pantoprazole",
    "ЭЗОМЕПРАЗОЛ": "Esomeprazole",
    "ФАМОТИДИН": "Famotidine",
    "ЛОПЕРАМИД": "Loperamide",
    "СМЕКТИТ ДИОКТАЭДРИЧЕСКИЙ": "Smectite",
    "ДРОТАВЕРИН": "Drotaverine",
    "ПАПАВЕРИН": "Papaverine",
    "АМБРОКСОЛ": "Ambroxol",
    "АЦЕТИЛЦИСТЕИН": "Acetylcysteine",
    "БРОМГЕКСИН": "Bromhexine",
    "САЛЬБУТАМОЛ": "Salbutamol",
    "БУДЕСОНИД": "Budesonide",
    "ЛОРАТАДИН": "Loratadine",
    "ЦЕТИРИЗИН": "Cetirizine",
    "ДЕЗЛОРАТАДИН": "Desloratadine",
    "ХЛОРОПИРАМИН": "Chloropyramine",
    "НАФАЗОЛИН": "Naphazoline",
    "КСИЛОМЕТАЗОЛИН": "Xylometazoline",
    "ОКСИМЕТАЗОЛИН": "Oxymetazoline",
    "ДИАЗЕПАМ": "Diazepam",
    "ЛОРАЗЕПАМ": "Lorazepam",
    "БРОМАЗЕПАМ": "Bromazepam",
    "ФЕНОБАРБИТАЛ": "Phenobarbital",
    "КАРБАМАЗЕПИН": "Carbamazepine",
    "ВАЛЬПРОЕВАЯ КИСЛОТА": "Valproic acid",
    "ЛЕВЕТИРАЦЕТАМ": "Levetiracetam",
    "ТРАМАДОЛ": "Tramadol",
    "МОРФИН": "Morphine",
    "ФЕНТАНИЛ": "Fentanyl",
    "АМИКАЦИН": "Amikacin",
    "ГЕНТАМИЦИН": "Gentamicin",
    "ВИНКРИСТИН": "Vincristine",
    "ДОКСОРУБИЦИН": "Doxorubicin",
    "ЦИКЛОФОСФАМИД": "Cyclophosphamide",
    "МЕТОТРЕКСАТ": "Methotrexate",
    "ТЕМОЗОЛОМИД": "Temozolomide",
    "ДАЗАТИНИБ": "Dasatinib",
    "ИМАТИНИБ": "Imatinib",
    "ДАРУНАВИР": "Darunavir",
    "ЛОПИНАВИР": "Lopinavir",
    "АТАЗАНАВИР": "Atazanavir",
    "ЗИДОВУДИН": "Zidovudine",
    "АБАКАВИР": "Abacavir",
    "ЛАМИВУДИН": "Lamivudine",
    "ТЕНОФОВИР": "Tenofovir",
    "ЭФАВИРЕНЗ": "Efavirenz",
    "КАПРЕОМИЦИН": "Capreomycin",
    "ИЗОНИАЗИД": "Isoniazid",
    "РИФАМПИЦИН": "Rifampicin",
    "ПИРАЗИНАМИД": "Pyrazinamide",
    "ЭТАМБУТОЛ": "Ethambutol",
    "ПРЕДНИЗОЛОН": "Prednisolone",
    "ДЕКСАМЕТАЗОН": "Dexamethasone",
    "ГИДРОКОРТИЗОН": "Hydrocortisone",
    "БЕТАМЕТАЗОН": "Betamethasone",
    "ЦИТРАМОН": "Citramon",
    "АНАЛЬГИН": "Metamizole",  # alt name
    "НОВОКАИН": "Procaine",  # alt
    "ГЛЮКОЗА": "Glucose",  # alt
    "НАФТИЗИН": "Naphazoline",  # alt
    "ЛЕВОМИЦЕТИН": "Chloramphenicol",  # alt
    "ГЛИЦЕРИН": "Glycerol",  # alt
}


def search_variants(name, mnn):
    """Build a list of (query, lang_priority) variants to try in order."""
    out = []
    if name:
        out.append((name, 5))  # exact Russian trade
    if mnn:
        out.append((mnn, 4))   # Russian MNN
        translit = MNN_TRANSLIT.get(mnn.upper())
        if translit:
            out.append((translit, 6))  # English MNN — usually best
    # dedupe preserving order
    seen, uniq = set(), []
    for v, p in out:
        if v.lower() in seen: continue
        seen.add(v.lower())
        uniq.append((v, p))
    return uniq
