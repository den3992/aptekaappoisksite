// Text formatting helpers used across the UI.
// The DB keeps drug names/forms/manufacturers in ALL CAPS for some sources
// (e.g. ESKLP registry). We don't mutate the DB — instead we normalise
// casing at render-time.

const isAllCaps = (s) => {
  if (!s || typeof s !== 'string') return false;
  const letters = s.match(/\p{L}/gu) || [];
  if (letters.length < 3) return false;
  const upper = letters.filter((c) => c === c.toUpperCase() && c !== c.toLowerCase());
  return upper.length / letters.length >= 0.85;
};

// Title-case ALL-CAPS strings: first letter of each word uppercase, rest lower.
// Keeps already-mixed-case strings untouched.
// Preserves short tokens that look like units/dosages (e.g. "мг", "мл", "МНН").
export function formatName(s) {
  if (!s || typeof s !== 'string') return s;
  if (!isAllCaps(s)) return s;
  return s
    .toLocaleLowerCase('ru-RU')
    .replace(/(^|[\s\-/(])(\p{L})/gu, (m, p1, p2) => p1 + p2.toLocaleUpperCase('ru-RU'));
}

// Legal-form prefixes (RU) that should be stripped from manufacturer names.
// Match at start of string OR at end (sometimes RU form goes after name).
const LEGAL_FORMS = [
  'ОАО', 'ООО', 'ЗАО', 'ПАО', 'НАО', 'АО', 'ОДО', 'ИП',
  'ФГУП', 'ФГБУ', 'ГБУ', 'ГУП', 'ГП', 'ФКП',
  'ПФК', 'НПО', 'НПП', 'НПК', 'ПКФ', 'ХФК', 'ФП',
  'OOO', 'AO', 'OAO', 'PAO', // Latin look-alikes used by some scrapers
];

// Foreign legal-form suffixes (anywhere in the string) — used to detect
// "tail" after a comma that should be stripped (e.g. "КРКА, Д.Д., НОВО МЕСТО").
// Each entry is matched as a whole token (Cyrillic-aware).
const FOREIGN_LEGAL_TOKENS = [
  // Russian-transliterated legal forms (with dot variants)
  'Д.Д.', 'Д.О.О.', 'СП. З.О.О.', 'З.О.О.', 'Н.В.', 'С.А.', 'С.А.У.',
  'С.П.А.', 'С.Р.Л.', 'С.Р.О.', 'С.Л.', 'С.Л.У.', 'С.А.С.', 'С.Л.Р.',
  'К.С.', 'К.Г.', 'К.Г.А.А.', 'М.Б.Х.', 'К.Б.',
  'А.Д.', 'А.О.', 'А.Ш.', 'А.С.', 'А.Е.', 'А.В.Е.', 'А.Б.',
  'Б.В.', 'Н.В.', 'П.К.', 'Л.Л.С.',
  'ГМБХ', 'ГмбХ', 'ЛТД.', 'ЛТД', 'ЛТДА.', 'ЛТДА',
  'СПА', 'АГ', 'СА', 'СЕ', 'ИНК', 'ИНК.',
  'КГ', 'ОГ', 'НФГ.', 'НФГ', 'ЛЛС', 'ЛЛК', 'МБХ', 'МбХ',
  'ПВТ.', 'ПВТ', 'ПЛК', 'ПЛК.', 'ПТЕ.', 'ПТЕ',
  'КО.', 'КО', 'ШИРКЕТИ', 'А.Ш.', 'АНОНИМ', 'ТИДЖ.', 'ТИДЖ',
  'ПРАЙВЕТ', 'ЛИМИТЕД',
  // Brand-noise tokens — strip when trailing/comma-tailing
  'ИНДАСТРИЗ', 'ЛАБОРАТОРИЗ', 'ЛАБОРАТОРИС', 'ЛАБОРАТОРИЕС',
  'ИНТЕРНЕШНЛ', 'ХЕЛСКЭР', 'ХЕЛСКЕА',
  'ХОЛДИНГ', 'ГРУПП', 'ГРУП',
  'КОМПАНИ', 'ИНКОРПОРЕЙТЕД',
  'САНАЙИ', 'ТИДЖАРЕТ', 'ИЛАЧ',
  // Latin
  'GMBH', 'GMBH.', 'LTD.', 'LTD', 'LLC', 'LLC.', 'INC.', 'INC', 'PLC', 'PLC.',
  'BV', 'B.V.', 'AG', 'A.G.', 'SA', 'S.A.', 'SAU', 'S.A.U.',
  'SARL', 'S.A.R.L.', 'SRL', 'S.R.L.', 'SPA', 'S.P.A.',
  'KG', 'KGAA', 'CO.', 'CO', 'AB', 'OY', 'KK', 'KFT',
  'COMPANY', 'COMPAGNIE', 'CORP', 'CORPORATION', 'INCORPORATED',
  'PVT.', 'PVT', 'LTDA', 'LTDA.', 'PTE.', 'PTE', 'SAS', 'S.A.S.',
  'ARZNEIMITTEL', 'PHARMA', 'PHARMACEUTICAL', 'PHARMACEUTICALS',
  'HEALTHCARE', 'LABORATORIES', 'LABORATORIS', 'INDUSTRIES', 'INDUSTRY',
  'HOLDING', 'GROUP', 'TRADING', 'INTERNATIONAL',
];

// Brand-override patterns: when manufacturer matches one of these regexes,
// return the canonical brand name directly (skipping the generic stripper).
// Patterns are tested case-insensitively against the FULL trimmed string.
// Order matters: more specific patterns should go first.
const BRAND_OVERRIDES = [
  // Russian-language uppercase variants from ЕСКЛП registry
  [/(^|[\s,])КРКА($|[\s,])/i, 'KRKA'],
  [/РЕКИТТ\s+БЕНКИЗЕР/i, 'Reckitt Benckiser'],
  [/ГЕДЕОН\s+РИХТЕР/i, 'Gedeon Richter'],
  [/САНОФИ(-АВЕНТИС)?(?![А-Я])/i, 'Sanofi'],
  [/ОПЕЛЛА\s+ХЕЛСК/i, 'Opella Healthcare'],
  [/НОВАРТИС/i, 'Novartis'],
  [/(ТАКЕДА|НИКОМЕД)/i, 'Takeda'],
  [/ПФАЙЗЕР/i, 'Pfizer'],
  [/ГЛАКСОСМИТКЛЯЙН|GLAXOSMITHKLINE|GSK/i, 'GSK'],
  [/ХЕЙЛКАЙР|ХЭЛЕОН|HALEON/i, 'Haleon'],
  [/(ЯНССЕН|КЕНВЬЮ|KENVUE)/i, 'Kenvue'],
  [/БЕРИНГЕР\s+ИНГЕЛЬХАЙМ/i, 'Boehringer Ingelheim'],
  [/ШТАДА|STADA|НИЖФАРМ/i, 'Stada'],
  [/(ЮНИК\s+ФАРМАСЬЮТИКАЛ|ЦИПЛА|CIPLA)/i, 'Cipla'],
  [/ТЕВА(?![А-Я])|САНДОЗ/i, 'Teva'],
  [/АСТРАЗЕНЕКА|ASTRAZENECA/i, 'AstraZeneca'],
  [/БАЙЕР|BAYER/i, 'Bayer'],
  [/ЭББОТТ|ABBOTT/i, 'Abbott'],
  [/БИОНОРИКА|BIONORICA/i, 'Bionorica'],
  [/КРЕВЕЛЬ\s+МОЙЗЕЛЬБАХ|KREWEL/i, 'Krewel Meuselbach'],
  [/УРСАФАРМ|URSAPHARM/i, 'Ursapharm'],
  [/МАТЕРИА\s+МЕДИКА/i, 'Materia Medica'],
  [/ФИРН\s+М/i, 'Фирн-М'],
  [/ЦИТОМЕД/i, 'Цитомед'],
  [/СОФАРИМЕКС/i, 'Sofarimex'],
  [/(^|[\s,])МЕРК(\s+КГАА|\s+ШАРП|$|[\s,])/i, 'Merck'],
  [/ФАРМСТАНДАРТ/i, 'Фармстандарт'],
  [/(^|\s)ОЗОН(\s+ФАРМ)?($|\s|,)/i, 'Озон'],
  [/КАНОНФАРМА/i, 'Канонфарма'],
  [/(^|[\s,])АКРИХИН($|[\s,])/i, 'Акрихин'],
  [/БИОХИМИК/i, 'Биохимик'],
  [/ВЕЛФАРМ/i, 'Велфарм'],
  [/АВВА\s+РУС/i, 'АВВА РУС'],
  [/НПО\s+МИКРОГЕН|МИКРОГЕН/i, 'Микроген'],
  [/ОТИСИФАРМ|ОТЦИФАРМ|ОТЦФАРМ/i, 'Otcpharm'],
  [/(^|[\s,])ВЕРТЕКС($|[\s,])/i, 'Вертекс'],
  [/ПФК\s+ОБНОВЛЕНИЕ|ОБНОВЛЕНИЕ\s+ПФК|(^|\s)ОБНОВЛЕНИЕ(\s|$)/i, 'Renewal'],
  [/(^|[\s,])БИОКАД($|[\s,])|BIOCAD/i, 'Биокад'],
  [/(^|[\s,])Р-ФАРМ($|[\s,])|R-PHARM/i, 'Р-Фарм'],
  [/(^|[\s,])ГЕНЕРИУМ($|[\s,])|GENERIUM/i, 'Generium'],
  [/(^|[\s,])НАТИВА($|[\s,])|NATIVA/i, 'Nativa'],
  [/(^|[\s,])ФАРМАСИНТЕЗ|PHARMASYNTEZ/i, 'Фармасинтез'],

  // More international top brands
  [/НОВО\s+НОРДИСК|NOVO\s+NORDISK/i, 'Novo Nordisk'],
  [/ЭЛИ\s+ЛИЛЛИ|LILLY/i, 'Eli Lilly'],
  [/БРИСТОЛ-?МАЙЕРС\s+СКВИББ|BRISTOL/i, 'Bristol-Myers Squibb'],
  [/РОШ|ROCHE|ГЕНЕНТЕК|GENENTECH/i, 'Roche'],
  [/ДЖОНСОН\s+(И|&)\s+ДЖОНСОН|JOHNSON\s*&\s*JOHNSON/i, 'Johnson & Johnson'],
  [/АСТЕЛЛАС|ASTELLAS/i, 'Astellas'],
  [/БОШ\s+ЛОМБ|BAUSCH\s+(\+|&)\s+LOMB/i, 'Bausch & Lomb'],
  [/ЭББВИ|ABBVIE/i, 'AbbVie'],
  [/АЛЛЕРГАН|ALLERGAN/i, 'Allergan'],
  [/АМДЖЕН|AMGEN/i, 'Amgen'],
  [/БОФУР\s+ИПСЕН|БЕАУФОР|IPSEN/i, 'Ipsen'],
  [/СЕЛДЖЕН|CELGENE/i, 'Celgene'],
  [/ГИЛИАД|GILEAD/i, 'Gilead'],
  [/ВИАТРИС|VIATRIS|МАЙЛАН|MYLAN/i, 'Viatris'],
  [/АСПЕН|ASPEN/i, 'Aspen'],
  [/УОРНЕР\s+ЧИЛКОТТ|WARNER/i, 'Warner Chilcott'],
  [/ХЕМОФАРМ|HEMOFARM/i, 'Hemofarm'],
  [/ШРЕЯ\s+ЛАЙФ/i, 'Shreya Life Sciences'],
  [/ДЖОДАС\s+ЭКСПОИМ/i, 'Jodas Expoim'],
  [/САН\s+ФАРМАСЬЮТИКАЛ|SUN\s+PHARMA/i, 'Sun Pharma'],
  [/ИПКА\s+ЛАБОРАТОРИЗ|IPCA/i, 'Ipca'],
  [/НОБЕЛ\s+ИЛАЧ|NOBEL/i, 'Nobel İlaç'],
  [/СЕНТИСС\s+ФАРМА|SENTISS/i, 'Sentiss'],
  [/ЗИГФРИД\s+БАРБЕРА|SIEGFRIED/i, 'Siegfried'],
  [/УОРЛД\s+МЕДИЦИН/i, 'World Medicine'],
  [/ФАРМАТЕН|PHARMATHEN/i, 'Pharmathen'],
  [/ОКТАФАРМА|OCTAPHARMA/i, 'Octapharma'],
  [/ОНКОМЕД|ONCOMED/i, 'OncoMed'],
  [/АЛКАЛОИД|ALKALOID/i, 'Alkaloid'],
  [/ПОЛЬФА|POLPHARMA/i, 'Polpharma'],
  [/КОН-ФАРМА|KONPHARMA/i, 'Кон-Фарма'],
  [/А\.\s*МЕНАРИНИ|MENARINI/i, 'Menarini'],
  [/ДОКТОР\s+ВИЛЬМАР\s+ШВАБЕ|SCHWABE/i, 'Dr. Willmar Schwabe'],
  [/НАТТЕРМАНН|NATTERMANN/i, 'Nattermann'],
  [/РЕКОРДАТИ|RECORDATI/i, 'Recordati'],
  [/ПАТЕОН|PATHEON/i, 'Patheon'],
  [/ПРОТЕКХ\s+БИОСИСТЕМС/i, 'Protech Biosystems'],
  [/ОКСФОРД\s+ЛАБОРАТОРИЗ/i, 'Oxford Laboratories'],
  [/СИМПЕКС\s+ФАРМА/i, 'Simpex Pharma'],
  [/ХАЙГЛАНС/i, 'Highglance Laboratories'],
  [/НАБРОС\s+ФАРМА/i, 'Nabros Pharma'],
  [/НОВАЛЕК/i, 'Novalek'],
  [/ЛОК-БЕТА/i, 'Lok-Beta'],
  [/М\.?\s*ДЖ\.?\s*БИОФАРМ/i, 'M.J. Biopharm'],
  [/САНОВЕЛЬ|SANOVEL/i, 'Sanovel'],
  [/КАРНАТАКА\s+АНТИБИОТИКС/i, 'Karnataka Antibiotics'],
  [/АЙПИЭР/i, 'IPER Pharmaceutical'],
  [/ДАНАФА/i, 'Danapha'],
  [/РЕЙОНГ/i, 'Rayong Pharmaceutical'],
  [/СИНТОН/i, 'Synthon'],
  [/ОРГАНОН|ORGANON/i, 'Organon'],
  [/ФАМАР|FAMAR/i, 'Famar'],
  [/ЭЙЧ\s+БИ\s+ЭМ\s+ФАРМА/i, 'HBM Pharma'],
  [/ФАРМЗАВОД\s+ЕЛЬФА/i, 'Farmzavod Elfa'],
  [/ПРО\.?\s*МЕД\.?\s*ЦС/i, 'Pro.Med.CS Praha'],
  [/ЭКСЕЛЛА/i, 'Excella'],
  [/ТАРХОМИНСКИЙ.*ПОЛЬФА/i, 'Polfa Tarchomin'],
  [/ВАРШАВСКИЙ.*ПОЛЬФА/i, 'Polfa Warszawa'],
  [/ДЕЛЬФАРМ|DELPHARM/i, 'Delpharm'],
  [/КЛАБ\s+ХАРКАНИ|HUNGARO|EGIS/i, 'Egis'],
  [/ПОЛИФАРМ\s+ИНДАСТРИЗ/i, 'Polyfarm'],

  // Russian state/research institutions — keep brand-short
  [/ФГБУ.*БЛОХИНА/i, 'НМИЦ онкологии Блохина'],
  [/ФГБУ.*ЧУМАКОВА/i, 'ФНЦИРИП Чумакова'],
  [/ФГБУ.*ГАМАЛЕИ|МЕДГАМАЛ/i, 'НИЦЭМ Гамалеи'],
  [/НАЦИОНАЛЬНЫЙ\s+МЕДИЦИНСКИЙ.*КАРДИОЛОГИИ/i, 'НМИЦ кардиологии'],
  [/НИИ\s+ВАКЦИН\s+И\s+СЫВОРОТОК/i, 'НИИ вакцин и сывороток'],
  [/БЕЛМЕДПРЕПАРАТЫ/i, 'Белмедпрепараты'],
  [/МИНСКИНТЕРКАПС/i, 'Минскинтеркапс'],
  [/БОРИСОВСКИЙ.*МЕДИЦИНСКИХ/i, 'Борисовский ЗМП'],
  [/БАРНАУЛЬСКИЙ.*МЕДИЦИНСКИХ/i, 'Барнаульский ЗМП'],
  [/ИССЛЕДОВАТЕЛЬСКИЙ\s+ИНСТИТУТ\s+ХИМИЧЕСКОГО\s+РАЗНООБРАЗИЯ/i, 'ИИХР'],
  [/ХИМИКО-ФАРМАЦЕВТИЧЕСКИЙ\s+ЗАВОД/i, 'Химфармзавод'],
  [/ИНСТИТУТ\s+БИООРГАНИЧЕСКОЙ\s+ХИМИИ/i, 'Институт биоорг. химии НАНБ'],
  [/ОБНИНСКАЯ\s+ХИМИКО-ФАРМАЦЕВТИЧЕСКАЯ/i, 'Обнинская ХФК'],
  [/ОМУТНИНСКАЯ.*ОПЫТНО-ПРОМЫШЛЕННАЯ/i, 'Омутнинская НОПБ'],
  [/КЕМЕРОВСКАЯ\s+ФАРМАЦЕВТИЧЕСКАЯ\s+ФАБРИКА/i, 'Кемеровская ФФ'],
  [/ЯРОСЛАВСКАЯ\s+ФАРМАЦЕВТИЧЕСКАЯ\s+ФАБРИКА/i, 'Ярославская ФФ'],
  [/ТУЛЬСКАЯ\s+ФАРМАЦЕВТИЧЕСКАЯ\s+ФАБРИКА/i, 'Тульская ФФ'],
  [/ЕРЕВАНСКАЯ\s+ХИМИКО-ФАРМАЦЕВТИЧЕСКАЯ/i, 'Ереванская ХФФ'],
  [/ФАРМАЦЕВТИЧЕСКАЯ\s+ФАБРИКА\s+САНКТ-ПЕТЕРБУРГА/i, 'Санкт-Петербургская ФФ'],
  [/ГОМЕОПАТИЧЕСКИЙ\s+МЕДИКО-СОЦИАЛЬНЫЙ/i, 'Гомеопатический центр'],
  [/ХОЛДИНГ\s+ЭДАС/i, 'ЭДАС'],
  [/ФАРММЕНТАЛ/i, 'Фармментал'],
  [/АЛИУМ/i, 'Алиум'],
  [/НПФ\s+МАТЕРИА\s+МЕДИКА/i, 'Materia Medica'],
  [/ХИНОИН/i, 'Chinoin'],
  [/ОАО\s+НЕСВИЖСКИЙ.*МЕДИЦИНСКИХ/i, 'Несвижский ЗМП'],
  [/ФАРМАСЬЮТИКАЛ\s+МАНУФЭКЧУРИНГ\s+РИСЕРЧ/i, 'Pharmaceutical Manufacturing Research'],
  [/ДР\.?\s*ГЕРХАРД\s+МАНН|DR\.?\s*MANN/i, 'Dr. Mann Pharma'],
  [/АМВ\s+ГМБХ.*ВАРНГАУ/i, 'AMW Arzneimittelwerk'],
  [/РОМФАРМ\s+ИЛАЧ|ROMPHARM/i, 'Rompharm'],
  [/ХАСКО-ЛЕК|HASCO-LEK/i, 'Hasco-Lek'],
  [/КЬЕЗИ|CHIESI/i, 'Chiesi'],
  [/УНИ-ФАРМА\s+КЛЕОН|UNI-PHARMA/i, 'Uni-Pharma'],
  [/ГЛЕНМЕРИ\s+БИОТЕХНОЛОДЖИС|GLENMERY/i, 'Glenmery Biotech'],
  [/АЛЕКСАНДРИЯ\s+ХИМИКО|ХИМИКО.*АЛЕКСАНДРИЯ/i, 'Alexandria CPI'],
  [/НОРТ\s+ЧАЙНА\s+ФАРМАСЬЮТИКАЛ|NORTH\s+CHINA\s+PHARMACEUTICAL/i, 'NCPC'],
  [/АВАРА\s+ЛИСКАТЕ/i, 'Avara Liscate'],
  [/МАИНЛУН|MAINLUNG/i, 'Mainlung Pharmaceutical'],
  [/ХЕННИГ\s+АРЦНАЙМИТТЕЛЬ|HENNIG/i, 'Hennig Arzneimittel'],
  [/ФУДЗИ\s+ЯКУХИН|FUJI\s+YAKUHIN/i, 'Fuji Yakuhin'],
  [/ТРОММСДОРФФ|TROMMSDORFF/i, 'Trommsdorff'],
  [/ЛЕМЕРИ|LEMERY/i, 'Lemery'],
  [/ЛИОФИЛИЗЕЙШН\s+СЕРВИСЕЗ/i, 'Lyophilization Services'],
  [/ХАНЧЖОУ\s+ЧЖУНМЭЙ\s+ХУАДУН|HANGZHOU/i, 'Hangzhou Zhongmei Huadong'],
  [/МОСХИМФАРМПРЕПАРАТЫ|МХФП/i, 'Мосхимфармпрепараты'],
  [/РНПЦ\s+ТРАНСФУЗИОЛОГИИ/i, 'РНПЦ трансфузиологии'],
  [/НМИЦК.*ЧАЗОВА|КАРДИОЛОГИИ.*ЧАЗОВА/i, 'НМИЦ кардиологии Чазова'],
  [/ПРОТИВОЧУМНЫЙ\s+ИНСТИТУТ\s+МИКРОБ/i, 'НИПЧИ Микроб'],
  [/КАРАГАНДИНСКИЙ\s+ФАРМАЦЕВТИЧЕСКИЙ/i, 'Карагандинский ФК'],
  [/ЦЕНТР\s+ГЕННОЙ\s+ИНЖЕНЕРИИ/i, 'Центр генной инженерии'],
  [/ШУГАИ\s+ФАРМА|CHUGAI/i, 'Chugai Pharma'],
  [/МОНТАВИТ|MONTAVIT/i, 'Montavit'],
  [/МИКРОХИМ(?![А-Я])/i, 'Микрохим'],
  [/ТВЕРЬГАЗСЕРВИС/i, 'Тверьгазсервис'],
  [/ВЕРВАГ\s+ФАРМА|WORWAG/i, 'Wörwag Pharma'],
  [/ЭБЕВЕ\s+ФАРМА|EBEWE/i, 'Ebewe Pharma'],
  [/ЭЙСАЙ|EISAI/i, 'Eisai'],
  [/АНЖЕЛИНИ|ANGELINI|ACRAF/i, 'Angelini'],
  [/ПОЛЬ-БОСКАМП|POHL-BOSKAMP|G\.\s*POHL/i, 'Pohl-Boskamp'],
  [/ДЕНТИНОКС|DENTINOX/i, 'Dentinox'],
  [/ВАЙЕТ|WYETH/i, 'Wyeth'],
  [/ВЕТТЕР-ФАРМА|VETTER/i, 'Vetter Pharma'],
  [/АРТЕЗАН/i, 'Artesan'],
  [/АТЛАНТИК\s+ФАРМА/i, 'Atlantic Pharma'],
  [/РОНТИС/i, 'Rontis'],
  [/ЛИХТЕНХЕЛЬДТ/i, 'Lichtenheldt'],
  [/ГЛОБОФАРМ/i, 'Globopharm'],
  [/ДОЛОРГИТ/i, 'Dolorgiet'],
  [/САНУМ-КЕЛЬБЕК/i, 'Sanum-Kehlbeck'],
  [/МЕРЦ\s+ФАРМА|MERZ\s+PHARMA/i, 'Merz Pharma'],
  [/ЭНГЕЛЬХАРД\s+АРЦНАЙМИТТЕЛЬ|ENGELHARD/i, 'Engelhard Arzneimittel'],
  [/АЛЕКСИОН|ALEXION/i, 'Alexion'],
  [/ФЕРРИНГ|FERRING/i, 'Ferring'],
  [/АЙВЭКС/i, 'Ivax'],
  [/НОРТОН\s+ВОТЕРФОРД/i, 'Norton Waterford'],
  [/ПИ\s+ЭНД\s+ДЖИ\s+ХЭЛС|P&G\s+HEALTH/i, 'P&G Health'],
  [/Ц\.?П\.?М\.?\s+КОНТРАКТФАРМА|КОНТРАКТФАРМА/i, 'CPM Contractpharma'],
  [/ДЖНТЛ\s+КОНСЬЮМЕР/i, 'JNTL Consumer Health'],
  [/МСД\s+ИНТЕРНЕЙШНЛ|MERCK\s+SHARP/i, 'MSD'],
  [/ПОЛИСАН|POLYSAN/i, 'Полисан'],
  [/ЭСКОМ(?![А-Я])/i, 'ЭСКОМ'],
  [/НОБЕЛ\s+АЛМАТИНСКАЯ/i, 'Nobel Алматы'],
  [/ГЕНВЕОН/i, 'Genveon'],
  [/АЗИЕНДЕ\s+КИМИКЕ/i, 'Angelini ACRAF'],
  [/ЛУЗОМЕДИКАМЕНТА/i, 'Lusomedicamenta'],
  [/АПОТЭК\s+ПРОДУКЦИОН/i, 'Apotek Produktion'],
  [/ЛАБОРАТОРИОС\s+МЕДИКАМЕНТОС/i, 'Laboratorios Medicamentos'],
  [/ОМАН\s+ФАРМАСЬЮТИКАЛ/i, 'Oman Pharmaceutical'],
  [/АРМАВИРСКАЯ.*АПТЕЧНАЯ/i, 'Армавирская АПТ-база'],
  [/ГАЛЕНИКА|GALENIKA/i, 'Galenika'],
  [/НАУЧНО-ТЕХНОЛОГИЧЕСКАЯ.*ПОЛИСАН/i, 'Полисан'],
  [/СИБИРСКИЙ\s+ЦЕНТР\s+ФАРМАКОЛОГИИ/i, 'Сибирский ЦФБ'],
  [/НПК\s+ЭСКОМ|КОНЦЕРН\s+ЭСКОМ/i, 'ЭСКОМ'],
  [/ЕГИПЕТСКАЯ\s+МЕЖДУНАРОДНАЯ/i, 'Egyptian Int. Pharma'],
  [/СЕВЕРНАЯ\s+КИТАЙСКАЯ/i, 'NCPC'],
  [/СЫЧУАНЬСКАЯ/i, 'Sichuan Yuanda'],
  [/ХЭБЭЙ\s+ХУАМИНЬ/i, 'Hebei Huamin'],
  [/ХИНОИН/i, 'Chinoin'],
  [/НОВЕЛЛ\s+ФАРМАСЬЮТИКАЛ/i, 'Novell Pharma'],
  [/МЕКОФАР/i, 'Mekophar'],
  [/ДОДЖИН\s+ИЯКУ-КАКО/i, 'Dojin Iyaku-Kako'],
  [/ФАРМАЦЕВТИЧЕСКАЯ\s+КОМПАНИЯ\s+АЛИУМ|АЛИУМ(?![А-Я])/i, 'Алиум'],
  [/НАУЧНО-ПРОИЗВОДСТВЕННЫЙ\s+КОНЦЕРН\s+ПОЛИСАН|КОНЦЕРН\s+ПОЛИСАН/i, 'Полисан'],
  [/ОБНИНСКАЯ\s+ХИМИКО-ФАРМАЦЕВТИЧЕСКАЯ/i, 'Обнинская ХФК'],
  [/ТЮМЕНСКИЙ\s+ХИМИКО-ФАРМАЦЕВТИЧЕСКИЙ/i, 'Тюменский ХФЗ'],
  [/ФАРМАЦЕВТИЧЕСКАЯ\s+ФАБРИКА\s+САНКТ-ПЕТЕРБУРГА/i, 'Санкт-Петербургская ФФ'],
  [/ФГАНУ\s+ФНЦИРИП|ФНЦИРИП/i, 'ФНЦИРИП'],
  [/ФКУЗ\s+РОСНИПЧИ\s+МИКРОБ/i, 'НИПЧИ Микроб'],
  [/ФКУЗ\s+СТАВРОПОЛЬСКИЙ\s+ПРОТИВОЧУМНЫЙ/i, 'Ставропольский ПЧИ'],
  [/ФБУ\s+НАУКИ\s+РОСТОВСКИЙ\s+НИИ/i, 'Ростовский НИИ микробиологии'],
  [/ФГАОУ?\s*О?У?\s*ВО?\s+РОССИЙСКИЙ\s+УНИВЕРСИТЕТ\s+ДРУЖБЫ/i, 'РУДН'],
  [/ФГБУ\s+48.*НИИ\s+МИНИСТЕРСТВА\s+ОБОРОНЫ/i, '48 ЦНИИ МО РФ'],
  [/НИЦ\s+48\s+ЦНИИ\s+МИНИСТЕРСТВА/i, '48 ЦНИИ МО РФ'],
  [/ВАЙЕТ\s+ФАРМАСЬЮТИКАЛЗ.*ВАЙЕТ\s+ХОЛДИНГЗ/i, 'Wyeth'],
  [/ЛИЛЛИ\s+ДЕЛЬ\s+КАРИБЕ/i, 'Eli Lilly del Caribe'],
  [/ВОЛОГОДСК.*СТАНЦИЯ\s+ПЕРЕЛИВАНИЯ/i, 'Вологодская ОСПК'],
  [/ИВАНОВСК.*СТАНЦИЯ\s+ПЕРЕЛИВАНИЯ/i, 'Ивановская ОСПК'],
  [/САМАРСК.*СТАНЦИЯ\s+ПЕРЕЛИВАНИЯ/i, 'Самарская ОСПК'],
  [/ТАМБОВСК.*СТАНЦИЯ\s+ПЕРЕЛИВАНИЯ/i, 'Тамбовская ОСПК'],
  [/ТЮМЕНСК.*СТАНЦИЯ\s+ПЕРЕЛИВАНИЯ/i, 'Тюменская ОСПК'],
  [/НИЖЕГОРОДСК.*ЦЕНТР\s+КРОВИ/i, 'Нижегородский ОЦК'],
  [/НПК\s+МЗ\s+РФ/i, 'Российский кардио-НПК'],
  [/ОБЛАСТНАЯ\s+СТАНЦИЯ\s+ПЕРЕЛИВАНИЯ\s+КРОВИ/i, 'ОСПК'],
  [/АО\s+КЕМЕРОВСКАЯ\s+ФАРМАЦЕВТИЧЕСКАЯ\s+ФАБРИКА/i, 'Кемеровская ФФ'],
  [/ОАО\s+КЕМЕРОВСКАЯ\s+ФАРМАЦЕВТИЧЕСКАЯ\s+ФАБРИКА/i, 'Кемеровская ФФ'],
  [/ДОКТОР\s+ГУСТАВ\s+КЛЯЙН/i, 'Dr. Gustav Klein'],
  [/ХАБЭЙ\s+ХУАМИНЬ/i, 'Hebei Huamin'],
  [/Г\.\s*ПОЛЬ-БОСКАМП/i, 'G. Pohl-Boskamp'],
];

// "Weak" canonical roots — too generic to use as a group key alone.
// When formatManufacturer returns one of these as the first word, we extend
// the canonical key with the next word to avoid merging unrelated companies.
const WEAK_ROOTS = new Set([
  'фирма', 'завод', 'фабрика', 'комбинат', 'институт', 'центр',
  'предприятие', 'объединение', 'компания', 'корпорация',
  'фармацевтический', 'фармацевтическая',
]);

// Short ALL-CAPS tokens that are likely real abbreviations — keep as-is.
const KEEP_ABBR = new Set([
  'ХФЗ', 'НПО', 'АХФ', 'ХФК', 'РФ', 'МНН', 'ЦМТ',
  'РУС', 'НПП', 'НПК', 'СНГ', 'СПБ',
]);

function titleWord(w) {
  if (!w) return w;
  // pure numeric tokens, punctuation
  if (!/\p{L}/u.test(w)) return w;
  // ALL-CAPS Cyrillic with NO vowels — likely real abbreviation (ХФЗ, НПО, ВДВ)
  if (w === w.toUpperCase() && /^[А-ЯЁ]+$/.test(w) && !/[АЕЁИОУЫЭЮЯ]/.test(w)) return w;
  // Curated abbreviations list — keep
  if (KEEP_ABBR.has(w)) return w;
  // standard title-case
  return w.charAt(0).toLocaleUpperCase('ru-RU') + w.slice(1).toLocaleLowerCase('ru-RU');
}

export function formatManufacturer(s) {
  if (!s || typeof s !== 'string') return s;
  const trimmed = s.trim().replace(/[«»"]/g, '');

  // 1. Brand-override fast-path: known multi-word brand names like
  //    "АО КРКА, Д.Д., НОВО МЕСТО" → "KRKA".
  for (const [re, brand] of BRAND_OVERRIDES) {
    if (re.test(trimmed)) return brand;
  }

  let v = trimmed;
  // Strip leading legal form(s), possibly several (e.g. "АО НПО МИКРОГЕН")
  // \b doesn't work with cyrillic in JS regex, so we use lookahead for separator.
  let changed = true;
  while (changed) {
    changed = false;
    for (const lf of LEGAL_FORMS) {
      const re = new RegExp(`^${lf}(?=\\s|[.,]|$)[\\s.,]*`, 'i');
      if (re.test(v)) {
        v = v.replace(re, '');
        changed = true;
      }
    }
  }
  // Strip trailing legal form ("ГЕДЕОН РИХТЕР ОАО")
  for (const lf of LEGAL_FORMS) {
    const re = new RegExp(`[\\s,]+${lf}\\s*$`, 'i');
    v = v.replace(re, '');
  }

  // 2. If a comma is followed by a foreign legal token anywhere downstream,
  //    cut at the first comma (drops "Д.Д., НОВО МЕСТО" etc.).
  const commaIdx = v.indexOf(',');
  if (commaIdx > 0) {
    const tail = v.slice(commaIdx + 1).toUpperCase();
    const tailHasLegal = FOREIGN_LEGAL_TOKENS.some((tok) => {
      // exact token match in tail (delimited by space/comma/dot)
      const re = new RegExp(`(^|[\\s,.])${tok.replace(/\./g, '\\.')}(?=$|[\\s,.])`);
      return re.test(tail);
    });
    if (tailHasLegal) v = v.slice(0, commaIdx);
  }

  // 3. Trailing foreign legal tokens — strip iteratively until stable
  //    (handles chains like "ПВТ. ЛТД.", "ГМБХ И КО. КГ", "Ко.ЛТД").
  {
    // Tokens that are SAFE to strip even if last (proper legal forms).
    // Excludes PHARMA/HEALTHCARE/LABORATORIES/INDUSTRIES/HOLDING/GROUP —
    // these are often part of the brand itself ("Sun Pharma", "Opella Healthcare").
    const SAFE_TRAIL = FOREIGN_LEGAL_TOKENS.filter((t) => !/(PHARMA|HEALTHCARE|LABORATOR|INDUSTR|HOLDING|GROUP|TRADING|INTERNATIONAL|КОМПАНИ|ИНДАСТРИЗ|ЛАБОРАТОРИ|ИНТЕРНЕШНЛ|ХОЛДИНГ|ГРУПП|ХЕЛСК|COMPANY|COMPAGNIE|ARZNEIMITTEL|PHARMACEUTICAL)/i.test(t));
    let prev = '';
    let iterations = 0;
    while (prev !== v && iterations++ < 10) {
      prev = v;
      // strip glue patterns: "& КО.кг", "И КО.лтд", "ЭНД КО"
      v = v.replace(/[\s,]+(?:И|AND|ЭНД|&)\s*КО\.?\s*(?:КГ|ОГ|ЛТД|LTD|KG|OG)?\s*$/i, '').trim();
      v = v.replace(/[\s,.]+КО\.?\s*(?:ЛТД|LTD|КГ|KG|ОГ|OG|КГАА|KGAA)\s*$/i, '').trim();
      v = v.replace(/[\s,]+КО\.?\s*$/i, '').trim();
      // strip orphan connector (e.g. "ГМБХ И" → "ГМБХ")
      v = v.replace(/[\s,]+(?:И|AND|ЭНД|&)\s*$/i, '').trim();
      for (const tok of SAFE_TRAIL) {
        const re = new RegExp(`[\\s,.]+${tok.replace(/\./g, '\\.')}\\s*$`, 'i');
        v = v.replace(re, '');
      }
    }
  }

  // 4. Strip trailing punctuation/dot artifacts
  v = v.trim().replace(/[\s.,;:]+$/, '').replace(/^[,\s]+/, '');
  if (!v) return s; // fallback if we stripped everything
  // Title-case only if input was mostly upper
  if (!isAllCaps(s)) return v;
  return v.split(/(\s+|[-/])/).map(titleWord).join('');
}

// Canonical "group root" for a manufacturer. Used to merge duplicate
// medication records that belong to the same pharma group but were registered
// by different legal entities (e.g. "Велфарм" + "Велфарм-М" → Велфарм).
//
// Returns a lowercase token suitable as a map/group key.
export function canonicalManufacturer(s) {
  const stripped = formatManufacturer(s);
  if (!stripped) return '';
  // Take the first dash-delimited token (drops "-М", "-Лексредства", "-Уфавита", "-Тюмень")
  // and the first whitespace-delimited token (drops trailing " Фарм", " М").
  const tokens = stripped.split(/[-/]/)[0].trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return '';
  let root = tokens[0].toLocaleLowerCase('ru-RU');
  // If first word is too generic (e.g. "ФИРМА"), include the next word
  // so "Фирма Здоровье" and "Фирма Фермент" don't collapse together.
  if (WEAK_ROOTS.has(root) && tokens.length > 1) {
    root = root + ' ' + tokens[1].toLocaleLowerCase('ru-RU');
  }
  return root;
}

// Group key for medication records that should appear as ONE search result.
// We dedupe by (name + form + dosage + canonical manufacturer group).
export function medGroupKey(m) {
  return [
    (m.name || '').toLocaleLowerCase('ru-RU').trim(),
    (m.form || '').toLocaleLowerCase('ru-RU').trim(),
    (m.dosage || '').toLocaleLowerCase('ru-RU').trim(),
    canonicalManufacturer(m.manufacturer),
  ].join('|');
}

// Deduplicate a list of meds: items sharing the same (name/form/dosage/group)
// are merged. The first item wins as the representative; other manufacturers
// from the same group are collected into `also_manufacturers` for display.
export function dedupeMeds(items) {
  if (!Array.isArray(items)) return items;
  const seen = new Map();
  for (const it of items) {
    const k = medGroupKey(it);
    if (!seen.has(k)) {
      seen.set(k, { ...it, also_manufacturers: [] });
    } else {
      const head = seen.get(k);
      const mfr = it.manufacturer;
      if (mfr && mfr !== head.manufacturer && !head.also_manufacturers.includes(mfr)) {
        head.also_manufacturers.push(mfr);
      }
    }
  }
  return Array.from(seen.values());
}

