"""
Pass 4: LLM-knowledge-driven translation + OMDB verification for the 634 remaining failures.

Uses a curated translation table (LLM knowledge) to map Spanish titles to known English/original
titles, then verifies each via OMDB before confirming to SoT.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from omdb_client import get_movie_details, broad_search_movie, search_movie_bilingual, _query_omdb, API_KEY
from source_of_truth import lookup_movie, update_movie, load_sot, save_sot

PENDING_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'pending_review.json')
CATALOGUE_NAME = 'CINE.pdf'
RATE_LIMIT = 1.1  # stay under 1 req/sec free tier limit
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# LLM knowledge table: Spanish catalog title (lowercase normalized) -> OMDB search title
# Used to bridge the gap when OMDB can't match the Spanish title directly.
# Each entry: (search_title, expected_director_fragment)  — director used for verification only
# ---------------------------------------------------------------------------
KNOWN_TRANSLATIONS = {
    "a media escalera": ("Grill Point", "dresen"),
    "adios al lenguaje": ("Goodbye to Language", "godard"),
    "ahi esta el detalle": ("Ahi esta el detalle", "bustillo"),
    "ahí esta el detalle": ("Ahi esta el detalle", "bustillo"),
    "agentes del desorden": ("Let's Be Cops", "),"),
    "ambiciosos, los": ("The Adventurers", ""),
    "amigos untouchable": ("The Intouchables", ""),
    "amo del juego. el": ("The Color of Money", ""),
    "amos de la dogtown.los": ("Lords of Dogtown", ""),
    "anaconda 2": ("Anacondas: The Hunt for the Blood Orchid", ""),
    "angel exterminador. el": ("The Exterminating Angel", "buñuel"),
    "angeles caidos fallen angels": ("Fallen Angels", "wong"),
    "angeles de charlie al limite": ("Charlie's Angels: Full Throttle", ""),
    "animales fantasticos": ("Fantastic Beasts and Where to Find Them", ""),
    "año del dragon.el": ("Year of the Dragon", "cimino"),
    "año nuevo del dragon.el": ("Year of the Dragon", "cimino"),
    "apuesta final rounders": ("Rounders", "dahl"),
    "arca rusa, el": ("Russian Ark", "sokurov"),
    "arma virtual so close": ("So Close", ""),
    "arte de matar,el 3": ("The Art of Killing 3", ""),
    "asesino dentro de mi, el": ("The Killer Inside Me", "winterbottom"),
    "asi del precipicio": ("Like This", ""),
    "atrapado sin salida": ("One Flew Over the Cuckoo's Nest", "forman"),
    "avalon gate to avalon": ("Avalon", ""),
    "barba roja": ("Red Beard", "kurosawa"),
    "bastardos sin gloria": ("Inglourious Basterds", "tarantino"),
    "batalla por la tierra": ("Battlefield Earth", ""),
    "bebe de rosemary, el": ("Rosemary's Baby", "polanski"),
    "beethoven monstruo inmortal": ("Frankenstein", ""),
    "belleza robada": ("Stealing Beauty", "bertolucci"),
    "bello durmiente, el": ("The Beautiful Dreamer", ""),
    "beowulf : la leyenda": ("Beowulf", "zemeckis"),
    "bernardita de lourdes": ("Bernadette", ""),
    "betty fisher y otras historias": ("Betty Fisher and Other Stories", "miller"),
    "bicicleta verde, la": ("Wadjda", "al-mansour"),
    "blanca nieves un cuento de terror": ("Snow White: A Tale of Terror", ""),
    "borat : el segudo mejor reportero": ("Borat", "charles"),
    "bordadoras, las": ("The Lacemaker", "goretta"),
    "brigada a -los magnificos the a-team": ("The A-Team", "carnahan"),
    "brigadas rojas": ("The Red Brigades", ""),
    "buda exploto de verguenza": ("Buddha Collapsed Out of Shame", "makhmalbaf"),
    "buenos dias noche": ("Good Morning, Night", "bellocchio"),
    "buenos muchachos goodfellas": ("Goodfellas", "scorsese"),
    "bufalo americano": ("American Buffalo", ""),
    "caceria voraz ii": ("Surviving the Game", ""),
    "cada loco con su tema": ("Each to His Own", ""),
    "cadena de favores": ("Pay It Forward", "leder"),
    "caida del halcon negro": ("Black Hawk Down", "scott"),
    "cambiamos pareja?": ("Blame It on Rio", ""),
    "camino del dragon. el": ("Way of the Dragon", "lee"),
    "campos de esperanza": ("Fields of Hope", ""),
    "canciones del segundo piso": ("Songs from the Second Floor", "andersson"),
    "capitan america y el soldado del invierno": ("Captain America: The Winter Soldier", ""),
    "carretera sangrienta": ("The Hills Have Eyes", ""),
    "casa silenciosa": ("The Silent House", ""),
    "casarse... esta en griego": ("My Big Fat Greek Wedding", "zwick"),
    "caza chicas, el  the pick-up artist": ("The Pick-up Artist", ""),
    "cazador de dinosaurios": ("Dinosaur Hunter", ""),
    "celular: llamada desesperada": ("Cellular", ""),
    "chicos y chicas": ("Boys and Girls", ""),
    "ciego, el, vida sin mi la,": ("Blind", ""),
    "cielo de octubre": ("October Sky", "johnston"),
    "cielo dividido, el": ("The Divided Heaven", "wolf"),
    "cien mujeres 100 girls": ("100 Girls", ""),
    "cinco segundos antes del fin del mundo": ("Five Seconds to Spare", ""),
    "cine en corto": ("Short Films", ""),
    "circulo de pasiones": ("Circle of Passion", ""),
    "cisne negro, el": ("Black Swan", "aronofsky"),
    "ciudad de dios city of god": ("City of God", "meirelles"),
    "ciudad virtual": ("eXistenZ", "cronenberg"),
    "ciudadano kane": ("Citizen Kane", "welles"),
    "clan del oso cavernario, el": ("The Clan of the Cave Bear", ""),
    "codigo de familia": ("Family Code", ""),
    "codigo de honor": ("Code of Honor", ""),
    "codigos de guerra": ("War Codes", ""),
    "coleccion de cortometrajes": ("Short Film Collection", ""),
    "color del crimen.el": ("Color of Crime", ""),
    "color purpura, el": ("The Color Purple", "spielberg"),
    "comando especial 21 jump street": ("21 Jump Street", ""),
    "comedia del poder, la": ("Comedy of Power", "chabrol"),
    "comer,beber, amar": ("Eat Drink Man Woman", "lee"),
    "como perder a tus amigos": ("How to Lose Friends & Alienate People", ""),
    "con las alas rotas": ("Broken Wings", ""),
    "conductor y el forastero. el": ("The Driver", ""),
    "conspiración descubierta": ("Conspiracy Theory", ""),
    "conspiración entre espias": ("Spy Games", ""),
    "contacto en rusia": ("The Spy Who Came in from the Cold", ""),
    "coronel redl": ("Colonel Redl", "szabo"),
    "correo explosivo": ("The Postman", ""),
    "cosecha del diablo/ prision maldita": ("The Devil's Harvest", ""),
    "crepusculo - luna nueva stephenie meyer": ("The Twilight Saga: New Moon", ""),
    "crimen virtual": ("Virtual Crime", ""),
    "cuando los hermanos se encuentran/ terciopelo": ("When Brothers Meet", ""),
    "cuervos": ("The Crows", ""),
    "cuervo, the crow": ("The Crow", "proyas"),
    "dalia negra, la": ("The Black Dahlia", "de palma"),
    "damas del mar": ("The Ladies of the Lake", ""),
    "danza con lobos": ("Dances with Wolves", "costner"),
    "daredevil : el hombre sin miedo": ("Daredevil", "johnson"),
    "david y betsabe": ("David and Bathsheba", ""),
    "de tal padre, tal hijo like father, like son": ("Like Father, Like Son", "koreeda"),
    "demasiada carne": ("Too Much Flesh", ""),
    "demonios en la puerta": ("Devils on the Doorstep", "jiang"),
    "desafio a los gigantes facing the gigants": ("Facing the Giants", ""),
    "descubriendo el pais de nunca jamas": ("Finding Neverland", "forster"),
    "dias de trueno": ("Days of Thunder", "scott"),
    "dias sin huella": ("The Lost Weekend", "wilder"),
    "diez cosas que odio de ti": ("10 Things I Hate About You", ""),
    "diez mil a.c.": ("10,000 BC", "emmerich"),
    "diez. la mujer perfecta": ("10", "edwards"),
    "discurso del rey, el the king's speech": ("The King's Speech", "hooper"),
    "django sin cadenas django unchained": ("Django Unchained", "tarantino"),
    "doble del diablo.el": ("The Devil's Double", "macdonald"),
    "doble riesgo": ("Double Jeopardy", ""),
    "dos mulas para la hermana sara": ("Two Mules for Sister Sara", "siegel"),
    "dracula principe de la tinieblas": ("Dracula: Prince of Darkness", ""),
    "dragon rojo": ("Red Dragon", "brett"),
    "drive el escape": ("Drive", "refn"),
    "duelo de titanes": ("Gunfight at the O.K. Corral", ""),
    "dura y peligrosa": ("Hard and Dangerous", ""),
    "duro de martar(un buen dia para morir": ("A Good Day to Die Hard", ""),
    "duro de matar 4.0": ("Live Free or Die Hard", "wiseman"),
    "escoces volador.el": ("Flying Scotsman", ""),
    "ecos mortales stir of echoes": ("Stir of Echoes", "koepp"),
    "edukadores,los": ("The Edukators", "weingartner"),
    "ella es unica": ("She's the One", ""),
    "enemigos publicos": ("Public Enemies", "mann"),
    "ensayo de orquesta": ("Orchestra Rehearsal", "fellini"),
    "equipo triunfador, el the mighty macs": ("The Mighty Macs", ""),
    "equis equis ye [i.e. xxy]": ("XXY", "puenzo"),
    "escandalos del rey jorge, los": ("The Madness of King George", ""),
    "escritores de la libertad": ("Freedom Writers", "lagravenese"),
    "escuadron gran rojo": ("The Big Red One", "fuller"),
    "escuela del rock": ("School of Rock", "linklater"),
    "especies iii": ("Species III", ""),
    "espejos siniestros mirrors": ("Mirrors", "aja"),
    "espionaje en berlin": ("Funeral in Berlin", ""),
    "ex mujer de mi vida, la": ("L'ex-femme de ma vie", ""),
    "expectro": ("The Spectre", ""),
    "expedientes secretos x": ("The X Files", ""),
    "expiacion, deseo y pecado": ("Atonement", "wright"),
    "expreso de media noche": ("Midnight Express", "parker"),
    "expreso de la muerte": ("Death Train", ""),
    "estranos:los": ("The Strangers", ""),
    "extranos en el paraiso": ("Stranger Than Paradise", "jarmusch"),
    "farenheit 451": ("Fahrenheit 451", "truffaut"),
    "fauces de la noche.las": ("Jaws of the Night", ""),
    "fenomeno siniestro 2": ("Phenomenon 2", ""),
    "fidel: libertador o dictador": ("Fidel", ""),
    "la fiesta inovidable the party": ("The Party", "edwards"),
    "furia en dos ruedas": ("Road Rage", ""),
    "gatopardo, el": ("The Leopard", "visconti"),
    "gattaca: experimento genetico": ("Gattaca", "niccol"),
    "gauguin:diario de un genio": ("Gauguin: Diary of a Genius", ""),
    "gendarme desconocido, el": ("The Unknown Gendarme", ""),
    "gente de roma gente di roma": ("Gente di Roma", "ettore"),
    "gigantes de acero": ("Real Steel", "levy"),
    "gotcha: juego de la muerte": ("Gotcha!", ""),
    "goya y la inquisicion": ("Goya in Bordeaux", "saura"),
    "gran papel, el": ("Big Eyes", ""),
    "grandes esperanzas": ("Great Expectations", ""),
    "gravedad gravity": ("Gravity", "cuaron"),
    "grbavica la revelacion de sara": ("Grbavica", "zbanic"),
    "greta garbo: ninotchka": ("Ninotchka", "lubitsch"),
    "gritos y susurros": ("Cries and Whispers", "bergman"),
    "guerra de novias": ("War of the Brides", ""),
    "guerreros de honor three swordsmen": ("Three Swordsmen", ""),
    "habitacion azul, la": ("The Blue Room", ""),
    "halcon maltes, el": ("The Maltese Falcon", "huston"),
    "historia americana x": ("American History X", "kaye"),
    "historia del camello que llora": ("The Story of the Weeping Camel", ""),
    "historia oficial, la": ("The Official Story", "puenzo"),
    "historia de sanson y dalila :la": ("Samson and Delilah", ""),
    "historias cruzadas the help": ("The Help", "taylor"),
    "historias de ultratumba": ("Tales from the Crypt", ""),
    "hitler: el nacimiento del mal": ("Hitler: The Rise of Evil", ""),
    "hollywood: departamento de homicidios": ("Hollywood Homicide", ""),
    "hombre de familia": ("The Family Man", "ratner"),
    "hombre de marmol": ("Man of Marble", "wajda"),
    "hombre en llamas man on fire tony scott": ("Man on Fire", "scott"),
    "hombre peligroso lord of war": ("Lord of War", "niccol"),
    "i.a. inteligencia artificial": ("A.I. Artificial Intelligence", "spielberg"),
    "ilusión viaja en tranvía, la": ("The Illusion Travels by Streetcar", "bunuel"),
    "imagenes del mas alla": ("Images of the Beyond", ""),
    "imperdonables unforgiven, los": ("Unforgiven", "eastwood"),
    "imperio del dragon.el": ("The White Dragon", ""),
    "incident en una carretera perdida": ("Incident on a Lost Road", ""),
    "informe pelicano, el": ("The Pelican Brief", "pakula"),
    "inframundo underworld": ("Underworld", "wiseman"),
    "instinto de media noche": ("Midnight Instinct", ""),
    "invasores del tesoro": ("Treasure Raiders", ""),
    "ira de los dioses, la": ("Wrath of the Gods", ""),
    "joven con el arete de perla, la": ("Girl with a Pearl Earring", "webber"),
    "jovenes brujas": ("The Craft", ""),
    "juana de arco": ("Joan of Arc", "besson"),
    "juego de ladrones": ("Heat", "mann"),
    "juego perfecto, el": ("The Perfect Game", ""),
    "juego sangriento": ("Deadly Game", ""),
    "juego y pasion": ("Game and Passion", ""),
    "juegos del corazon": ("Games of the Heart", ""),
    "juegos diabolicos poltergeist": ("Poltergeist", "hooper"),
    "juegos mortales": ("Saw", "wan"),
    "juegos, trampas y dos armas humeantes": ("Lock, Stock and Two Smoking Barrels", "ritchie"),
    "juez del apocalipsis,el": ("The Judge", ""),
    "julieta de los espiritus": ("Juliet of the Spirits", "fellini"),
    "kolya : el nombre de la esperanza": ("Kolya", "sverak"),
    "lado profundo del mar, el": ("The Deep Blue Sea", ""),
    "ladrona de corazon": ("Heart Thief", ""),
    "lagrimas del sol": ("Tears of the Sun", "fuqua"),
    "lawrence de arabia": ("Lawrence of Arabia", "lean"),
    "le havre el puerto de la esperanza": ("Le Havre", "kaurismaki"),
    "leyenda del fantasma. la": ("Ghost Legend", ""),
    "leyendas de pasion": ("Legends of the Fall", "zwick"),
    "leyendas de rita, las": ("The Legends of Rita", ""),
    "leyes de la atraccion, las": ("Laws of Attraction", ""),
    "lista de schindler, la": ("Schindler's List", "spielberg"),
    "liiston blanco, el": ("The White Ribbon", "haneke"),
    "llave de sarah, la": ("Sarah's Key", "paquet-brenner"),
    "lo que ellas quieren": ("What Women Want", ""),
    "lobo de wall street": ("The Wolf of Wall Street", "scorsese"),
    "locos de ira": ("Rage", ""),
    "luces distantes": ("Distant Lights", ""),
    "lugar sin limites, el": ("Place Without Limits", "ripstein"),
    "lujuria y traicion": ("Lust and Betrayal", ""),
    "lulu en el puente": ("Lulu on the Bridge", "auster"),
    "luna amarga": ("Bitter Moon", "polanski"),
    "luna de papel": ("Paper Moon", "bogdanovich"),
    "luna sangrienta": ("Blood Moon", ""),
    "mansion del panico": ("House of Fear", ""),
    "mantenidas sin suenos, las": ("The Kept Women", ""),
    "mapa a las estrellas maps to the stars": ("Maps to the Stars", "cronenberg"),
    "marabunta": ("Marabunta", ""),
    "mar abierto. el ojo": ("Open Water", ""),
    "maria llena eres de gracia": ("Maria Full of Grace", ""),
    "mas barato por docena": ("Cheaper by the Dozen", ""),
    "mas grande historia jamas contada": ("The Greatest Story Ever Told", ""),
    "mas negro que la noche": ("Blacker Than the Night", "taboada"),
    "masacre en nueva york": ("Maniac Cop", ""),
    "mataria por tu trabajo": ("I'll Kill for You", ""),
    "maxima riesgo": ("Cliffhanger", "harlin"),
    "mejor que el sexo": ("Better Than Sex", ""),
    "miedo punto com": ("Fear.Com", ""),
    "mil cuatrocientos noventa y dos: la conquista": ("1492: Conquest of Paradise", "scott"),
    "mil novecientos ochenta y cuatro =": ("Nineteen Eighty-Four", "radford"),
    "millenium mambo": ("Millennium Mambo", "hou"),
    "minority report sentencia previa": ("Minority Report", "spielberg"),
    "miroslava : manana, ya no estare aqui": ("Miroslava", ""),
    "mitad siniestra": ("The Dark Half", "romero"),
    "mi novio atomico blast from the past": ("Blast from the Past", ""),
    "mi pareja es mi rival": ("My Partner Is My Rival", ""),
    "mi vida como un perro": ("My Life as a Dog", "hallstrom"),
    "miedo punto com": ("Fear Dot Com", ""),
    "minas del rey salomon, las king slomon's mine": ("King Solomon's Mines", ""),
    "muhammad ali: el invencible": ("When We Were Kings", ""),
    "mundo cool": ("Cool World", "bakshi"),
    "muneca inflable": ("Lars and the Real Girl", ""),
    "muriendo por un sueno": ("Dying for a Dream", ""),
    "musica y lagrimas": ("Music and Tears", ""),
    "nicotina cuando el destino te da el golpe": ("Nicotina", ""),
    "nieves del kilimanjaro, las": ("The Snows of Kilimanjaro", ""),
    "nine [i.e.9] songs": ("9 Songs", "winterbottom"),
    "nino con el pijama de rayas, el": ("The Boy in the Striped Pyjamas", "herman"),
    "nino del sotano. el": ("The Kid in the Basement", ""),
    "ninos del brasil, los": ("The Boys from Brazil", "schaffner"),
    "ninos estan bien, los": ("The Kids Are All Right", "cholodenko"),
    "no amaras": ("Thou Shalt Not", ""),
    "no quiero dormir solo": ("I Don't Want to Sleep Alone", "tsai"),
    "no se si cortarme las venas o dejarmelas larg": ("I Don't Know How She Does It", ""),
    "no temas a la oscuridad": ("Don't Be Afraid of the Dark", ""),
    "noche de los muertos vivientes, la": ("Night of the Living Dead", "romero"),
    "noche del asesino": ("Night of the Killer", ""),
    "noche del crimen, la": ("Night of Crime", ""),
    "noche har shab tanhai, la": ("Night", ""),
    "noches purpura": ("Purple Nights", ""),
    "norteado": ("Northless", ""),
    "nosferatu, el vampiro": ("Nosferatu the Vampyre", "herzog"),
    "ojo 2. el": ("The Eye 2", ""),
    "ojos bien cerrados": ("Eyes Wide Shut", "kubrick"),
    "ojos de serpiente": ("Snake Eyes", "de palma"),
    "olvidate de paris": ("Forget Paris", "crystal"),
    "once:catorce [i.e. 11:14] : hora de morir": ("11:14", ""),
    "operacion dragon": ("Enter the Dragon", ""),
    "origen, el = inception  christopher nolan": ("Inception", "nolan"),
    "oro y cobre": ("Gold and Copper", ""),
    "otono en nueva york": ("Autumn in New York", ""),
    "otra cara de septiembre, la": ("The Other Side of September", ""),
    "otra huerfana.la": ("Orphan", "collet-serra"),
    "otra reina, la": ("The Other Boleyn Girl", ""),
    "otro lado del amor, el": ("The Other Side of Love", ""),
    "paciente ingles, el": ("The English Patient", "minghella"),
    "panico en altamar": ("Panic on the High Seas", ""),
    "pantanlon y las visitadoras": ("Captain Pantoja and the Special Services", "vargas llosa"),
    "papa por que te fuiste": ("Dad, Why Did You Leave", ""),
    "pare de pecar": ("Stop Sinning", ""),
    "parecido a la felicidad": ("Something Like Happiness", ""),
    "paris, clara y yo": ("Paris with Clara", ""),
    "partes usadas": ("Used Parts", ""),
    "pasion al atardecer": ("Dusk Passion", ""),
    "pasion de camile claudel camille claudel": ("Camille Claudel", "nuytten"),
    "pasion ilicita": ("Illicit Passion", ""),
    "pasion por africa": ("Passion for Africa", ""),
    "pasion segun berenice, la": ("Berenice", ""),
    "pasiones privadas en lugares publicos": ("Private Fears in Public Places", "resnais"),
    "pasiones secretas choses secretes": ("Secret Things", "brisseau"),
    "pauline y paulette": ("Pauline & Paulette", ""),
    "peligro hombres- trabajando": ("Men at Work", ""),
    "pequenas flores rojas": ("Little Red Flowers", ""),
    "pequenas heridas": ("Small Wounds", ""),
    "pequeno buda, el": ("Little Buddha", "bertolucci"),
    "pequeno fugitivo, el": ("The Little Fugitive", ""),
    "perfume de violetas": ("Perfume de violetas", ""),
    "perro rabio, el": ("Reservoir Dogs", "tarantino"),
    "perros de guerra, los": ("Dogs of War", ""),
    "pesadillas en la casa sombria": ("Haunted", ""),
    "pi, el orden del caos": ("Pi", "aronofsky"),
    "pieza final.la": ("The Final Piece", ""),
    "pijama para dos lover come back": ("Lover Come Back", ""),
    "pinceladas de fuego": ("Brushstrokes of Fire", ""),
    "piso 13 .el": ("The Thirteenth Floor", "rusnak"),
    "placer de la seda, el": ("The Silk Pleasure", ""),
    "plan 9 del espacio exterior": ("Plan 9 from Outer Space", "wood"),
    "planeta de los simios. revolucion. el": ("Rise of the Planet of the Apes", "wyatt"),
    "planeta salvaje, el": ("Fantastic Planet", "laloux"),
    "poison ivy 2 ( hiedra venenosa)": ("Poison Ivy II: Lily", ""),
    "por amor al arte the shape of things": ("The Shape of Things", "labute"),
    "por el lado oscuro del camino": ("On the Dark Side of the Road", ""),
    "poseidos .los ( tiene dos peliculas) y secta": ("The Possessed", ""),
    "posibilidad de escape": ("Escape Possibility", ""),
    "pozoamargo": ("Pozoamargo", ""),
    "precio de la codicia.el": ("The Price of Greed", ""),
    "precio del manana.el": ("In Time", "niccol"),
    "precious preciosa": ("Precious", "daniels"),
    "presagio knowing": ("Knowing", "proyas"),
    "presidente por un dia": ("President for a Day", ""),
    "princesa que queria vivir.la": ("The Princess Who Wanted to Live", ""),
    "prisionero del rock and roll": ("Rock and Roll Prisoner", ""),
    "procesos de las senoritas vivanco, el": ("Trial of the Vivanco Sisters", ""),
    "profundo carmesi": ("Deep Crimson", "ripstein"),
    "proyecto andromeda": ("The Andromeda Project", ""),
    "promesa de amor": ("Promise of Love", ""),
    "provocacion, la : match point": ("Match Point", "allen"),
    "proximo hombre, el": ("The Next Man", ""),
    "prueba de vida": ("Proof of Life", ""),
    "psi. i love you": ("P.S. I Love You", ""),
    "psicopata americano": ("American Psycho", "harron"),
    "pueblo perdido de switez,el": ("The Lost Village of Switez", ""),
    "rabino y el pistolero, el the frisco kid": ("The Frisco Kid", "aldrich"),
    "rapsodia en agosto rhapshody in august": ("Rhapsody in August", "kurosawa"),
    "recien enterrados": ("The Buried", ""),
    "red,  retirados extremadamente duros": ("RED", "schwentke"),
    "redondo ; tres historias de amor": ("Roundabout", ""),
    "reeker/la invasion de los muertos vivientes": ("Reeker", ""),
    "regreso a cold mountain": ("Cold Mountain", "minghella"),
    "regreso al presente": ("Back to the Future", ""),
    "reina de los condenados, la": ("Queen of the Damned", ""),
    "reina de persia": ("Queen of Persia", ""),
    "reinado del fuego, el": ("Reign of Fire", "bowman"),
    "replicant : asesino perfecto": ("Replicant", ""),
    "requiem por un imperio": ("Requiem for an Empire", ""),
    "requiem por un sueno": ("Requiem for a Dream", "aronofsky"),
    "retrato de una mujer casada": ("Portrait of a Married Woman", ""),
    "rio suzhou": ("Suzhou River", ""),
    "rito de la santa muerte, el": ("Rite of Santa Muerte", ""),
    "robin hood reynolds, kevin, 1952-": ("Robin Hood: Prince of Thieves", "reynolds"),
    "rojo como el cielo": ("Red Like the Sky", ""), 
    "roma ciudad abierta": ("Rome, Open City", "rossellini"),
    "romeo debe morir": ("Romeo Must Die", ""),
    "saint laurent saint laurent bonello, bertrand": ("Saint Laurent", "bonello"),
    "salems lot": ("Salem's Lot", ""),
    "salo, o, los 120 dias de sodoma": ("Salò, or the 120 Days of Sodom", "pasolini"),
    "salvaje rio, el": ("The River Wild", ""),
    "sandalias del pescador, las - the shoes of th": ("The Shoes of the Fisherman", ""),
    "sangre eterna": ("Eternal Blood", ""),
    "santo contra la hija de frankenstein": ("Santo vs. Frankenstein's Daughter", ""),
    "santo contra la mafia del vicio": ("Santo vs. the Mob of Vice", ""),
    "santo en la frontera del terror": ("Santo in the Frontier of Terror", ""),
    "santo en la venganza de la momia": ("Santo in the Vengeance of the Mummy", ""),
    "santo en la venganza de la momia azteca": ("Santo vs. the Aztec Mummy", ""),
    "santo vs el asesino de la television": ("Santo vs. the TV Killer", ""),
    "santo vs el espectro del estrangulador": ("Santo vs. the Strangler", ""),
    "santo y blue demon contra el dr. frankenstein": ("Santo and Blue Demon vs. Dr. Frankenstein", ""),
    "santo y blue demon en el mundo de los muertos": ("Santo and Blue Demon in the World of the Dead", ""),
    "santo y blue demon vs dracula y el hombre lob": ("Santo and Blue Demon vs. Dracula and the Wolf Man", ""),
    "santo y blue demon vs los monstruos": ("Santo and Blue Demon vs. the Monsters", ""),
    "scream3": ("Scream 3", "craven"),
    "se busca novia the bachelor": ("The Bachelor", ""),
    "se busca pareja must love dogs": ("Must Love Dogs", ""),
    "secreto de estado": ("State Secret", ""),
    "secretos de un matrimonio": ("Secrets of a Marriage", "bergman"),
    "secretos ocultos": ("Hidden Secrets", ""),
    "sensualidad de olga, la": ("The Sensuality of Olga", ""),
    "senales del mas alla": ("Signs from Beyond", ""),
    "senor de las moscas, el": ("Lord of the Flies", "brook"),
    "senora beba, la": ("Mrs. Beba", ""),
    "septiembre 11 varios directores": ("11'09''01 - September 11", ""),
    "serendipity , senales de amor": ("Serendipity", ""),
    "sexto dia, el  [i.e. sexto] 6 dia the 6th da": ("The 6th Day", "spottiswoode"),
    "shattered lives": ("Shattered Lives", ""),
    "shortbus: tu ultima parada": ("Shortbus", "mitchell"),
    "siempre a tu lado, hachiko": ("Hachi: A Dog's Tale", "hallstrom"),
    "siempre sabré lo que hiciste el verano pasado": ("I'll Always Know What You Did Last Summer", ""),
    "seis mujeres para un asesino": ("Blood and Black Lace", "bava"),
    "siete soles": ("Seven Suns", ""),
    "siete almas seven pounds": ("Seven Pounds", "muccino"),
    "siete copas, el": ("Seven Cups", ""),
    "siete samurai, los": ("Seven Samurai", "kurosawa"),
    "sin edad para el amor": ("No Age for Love", ""),
    "sr. sra. smith": ("Mr. & Mrs. Smith", "liman"),
    "sr. venganza": ("Sympathy for Mr. Vengeance", "park"),
    "sociedad de los poetas muertos": ("Dead Poets Society", "weir"),
    "solo contra si mismo": ("Alone Against Himself", ""),
    "sombras tenebrosas dark shadows": ("Dark Shadows", "burton"),
    "sonrisas de una noche de verano": ("Smiles of a Summer Night", "bergman"),
    "soy espia": ("Spy", ""),
    "starsky y hutch": ("Starsky & Hutch", "phillips"),
    "su nombre es jenifer": ("Jennifer Eight", ""),
    "sueno de walt saving mr. banks, el": ("Saving Mr. Banks", "hancock"),
    "suenos de akira kurosawa, los": ("Dreams", "kurosawa"),
    "suenos de orquesta": ("Orchestra Dreams", ""),
    "suenos ocultos": ("Hidden Dreams", ""),
    "super policias": ("Supercop", ""),
    "talentoso sr. ripley .el": ("The Talented Mr. Ripley", "minghella"),
    "tan espeso como el chocolate": ("Thick as Chocolate", ""),
    "tarea prohibida, la": ("Forbidden Task", ""),
    "taxi teheran": ("Taxi", "panahi"),
    "temporada de patos": ("Duck Season", "eimbcke"),
    "temporada de sequia": ("Dry Season", ""),
    "tercer tiro, el": ("The Third Shot", ""),
    "terror en chernobil": ("Chernobyl Diaries", ""),
    "testigo mudo": ("Silent Witness", ""),
    "the tenant(quimerico inquilino) el": ("The Tenant", "polanski"),
    "thomas esta enamorado": ("Thomas in Love", ""),
    "tiempo de mentir": ("Lying Time", ""),
    "la tiendita de los horrores the little shop o": ("Little Shop of Horrors", "oz"),
    "tomates verdes fritos": ("Fried Green Tomatoes", ""),
    "tonto pero no tanto billy madison": ("Billy Madison", ""),
    "tontos de altura": ("High Fools", ""),
    "tormenta de hielo ice storm": ("The Ice Storm", "lee"),
    "tragedia de franz woyzeck": ("Woyzeck", "herzog"),
    "traicinados": ("Betrayed", ""),
    "transportador, el": ("The Transporter", ""),
    "tras la tormenta": ("After the Storm", ""),
    "tras lineas enemigas behind enemy lines": ("Behind Enemy Lines", ""),
    "treinta dias de noche": ("30 Days of Night", "slade"),
    "treinta segundos antes de morir": ("Thirty Seconds Before Death", ""),
    "trenes rigurosamente vigilados": ("Closely Watched Trains", "menzel"),
    "tres mil [i.e.3000] millas al infierno": ("3000 Miles to Graceland", ""),
    "trece dias": ("Thirteen Days", "donaldson"),
    "el triangulo the triangle": ("The Triangle", ""),
    "tribunal en fuga": ("Runaway Jury", "fleder"),
    "truman show historia de una vida": ("The Truman Show", "weir"),
    "tutia  (pelicula irani)": ("Tutiya", ""),
    "tuya en septiembre": ("Yours in September", "mulligan"),
    "u-quinientos setenta y uno [i.e. 571] la bata": ("U-571", "mostow"),
    "ultima vida en el universo, la - ruang rak noi nid mahasan = last life in the universe pen-ek ratanaruang": ("Last Life in the Universe", ""),
    "ultimo camino, el": ("The Road", "hillcoat"),
    "ultimo emperador, el": ("The Last Emperor", "bertolucci"),
    "ultimo paciente chronic, el  franco, michel, 1979-": ("Chronic", "franco"),
    "ultimo samurai, el": ("The Last Samurai", "zwick"),
    "un amor inesperado": ("Surprises of Love", "reiner"),
    "un amor loco": ("A Mad Love", ""),
    "un amor muy especial": ("A Very Special Love", ""),
    "un amor surrealista marie & bruce": ("Marie and Bruce", ""),
    "un destello en la obscuridad": ("Prophecy", ""),
    "un domingo maravilloso": ("One Wonderful Sunday", "kurosawa"),
    "un dulce olor a muerte": ("A Sweet Scent of Death", ""),
    "un gato sobre el tejado caliente": ("Cat on a Hot Tin Roof", "brooks"),
    "un grito  antes de morir": ("A Cry in the Night", ""),
    "un hombre solitario": ("Solitary Man", "koppelman"),
    "un horizonte lejano": ("Far and Away", "howard"),
    "un milagro para henry": ("Henry Poole Is Here", "pellington"),
    "un milagro para lorenzo": ("Lorenzo's Oil", "miller"),
    "un oscuro secreto": ("A Lonely Place to Die", ""),
    "un perro andaluz": ("Un Chien Andalou", "bunuel"),
    "un puente demasiado lejos": ("A Bridge Too Far", "attenborough"),
    "un regalo sangriento": ("A Bloody Gift", ""),
    "una accion civil": ("A Civil Action", "zaillian"),
    "una aventura extraordinaria life of pi": ("Life of Pi", "lee"),
    "una chica perturbada": ("I Think I Love My Wife", ""),
    "una dama sin pudor": ("Irina Palm", "garbarski"),
    "una mente brillante": ("A Beautiful Mind", "howard"),
    "una muerte inesperada": ("Grace Is Gone", ""),
    "una sola entrega direccion y guion, oxide pang.": ("The Eye", "pang"),
    "unas dulces mentiras": ("Since Otar Left", "bertuccelli"),
    "usted es muy guapo": ("You Are So Beautiful", ""),
    "v de venganza": ("V for Vendetta", "mcteigue"),
    "vacaciones de invierno": ("National Lampoon's Christmas Vacation", "chechik"),
    "vacaciones de mr. bean": ("Mr. Bean's Holiday", "bendelack"),
    "valor bajo fuego": ("Courage Under Fire", "zwick"),
    "vecinos y enemigos": ("The Next Best Thing", ""),
    "veinticuatro cuadros de terror": ("24 Frames of Terror", ""),
    "veintisiete bodas": ("27 Dresses", "fletcher"),
    "veintun gramos": ("21 Grams", "inarritu"),
    "veintiún gramos": ("21 Grams", "inarritu"),
    "veneno para las hadas": ("Poison for the Fairies", "taboada"),
    "vengadora/testigos de un crimen": ("Witness to a Crime", ""),
    "vengador del futuro total recall wiseman, len, 1973-": ("Total Recall", "wiseman"),
    "venganza despiadada": ("Taken 3", "megaton"),
    "venganza yakuza": ("Yakuza Vengeance", ""),
    "ventajas de ser invisible guion y": ("The Perks of Being a Wallflower", "chbosky"),
    "ventana secreta, la": ("Secret Window", "koepp"),
    "vertigo/ la sombra  de una duda (doble dvd)": ("Vertigo", "hitchcock"),
    "vida prometida, la la vie promise = ghost river olivier dahan": ("La Vie Promise", "dahan"),
    "vidas en comun": ("Bedrooms and Hallways", "troche"),
    "violame baise-moi": ("Baise-moi", "despentes"),
    "violines en el cielo departures": ("Departures", "takita"),
    "virgen a los 40 anos": ("The 40-Year-Old Virgin", "apatow"),
    "virgen y culpable a los 41": ("The 41-Year-Old Virgin Who Knocked Up Sarah Marshall", ""),
    "virgenes suicidas, las": ("The Virgin Suicides", "s. coppola"),
    "vizconde de montecristo, el": ("The Viscount of Monte-Cristo", ""),
    "volando alto eddie the eagle": ("Eddie the Eagle", "fletcher"),
    "voraz raw": ("Raw", "ducournau"),
    "vuelven los siete magnificos": ("Return of the Seven", "kennedy"),
    "watchmen : relatos del navio negro": ("Watchmen: Tales of the Black Freighter", ""),
    "ward contra ward": ("Enough", "apted"),
    "y donde estan las rubias? white chicks": ("White Chicks", "wayans"),
    "yo amo huckabees": ("I Heart Huckabees", "russell"),
    "zapatillas rojas, las": ("The Red Shoes", "powell"),
    "zathura : una aventura fuera de este mundo": ("Zathura: A Space Adventure", "favreau"),
    "zona de miedo": ("Near Dark", "bigelow"),
    "zona muerta.la": ("The Dead Zone", "cronenberg"),
    # Short-title entries that may not have a director
    "amarillo mango assis, claudio,": ("Yellow Mango", ""),
    "cambiadora de paginas, la": ("The Page Turner", "dercourt"),
    "angela caidos fallen angels": ("Fallen Angels", ""),
    "bastardos sin gloria": ("Inglourious Basterds", "tarantino"),
    "buenos dias noche": ("Good Morning, Night", ""),
    "caceria voraz ii": ("Surviving the Game", ""),
    "ciudad de dios city of god": ("City of God", ""),
}


def normalize(s: str) -> str:
    """Normalize title for dict lookup."""
    s = s.lower().strip()
    # Remove accents simply by replacing common ones
    for a, b in [('á','a'),('é','e'),('í','i'),('ó','o'),('ú','u'),('ü','u'),('ñ','n'),
                  ('à','a'),('è','e'),('ì','i'),('ò','o'),('ù','u')]:
        s = s.replace(a, b)
    return s


def search_omdb_title(title: str) -> dict | None:
    """Try exact then fuzzy OMDB search for a title, with retry on rate-limit."""
    for attempt in range(MAX_RETRIES):
        try:
            r = _query_omdb({'t': title, 'type': 'movie', 'apikey': API_KEY})
            if r and r.get('imdbID') and r.get('Response') == 'True':
                return r
            time.sleep(RATE_LIMIT)
            r2 = _query_omdb({'s': title, 'type': 'movie', 'apikey': API_KEY})
            if r2 and r2.get('Search'):
                top = r2['Search'][0]
                iid = top.get('imdbID')
                if iid:
                    details = get_movie_details(iid)
                    time.sleep(RATE_LIMIT)
                    return details
            return None
        except Exception as e:
            if '401' in str(e) and attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt * 2
                time.sleep(wait)
                continue
            return None
    return None


def main():
    with open(PENDING_PATH, 'r', encoding='utf-8') as f:
        pending = json.load(f)

    failed = pending.get('failed_no_match', [])
    fuzzy = pending.get('fuzzy_candidates', [])
    print(f"Pass 4 (LLM translation table): processing {len(failed)} failed entries")

    newly_confirmed = []
    still_failed = []

    for i, entry in enumerate(failed):
        title_es = entry.get('title_spanish', '')
        director = entry.get('director', '')
        row_id = entry.get('id', '?')

        # Skip if already in SoT
        if lookup_movie(title_es):
            print(f"[{i+1}/{len(failed)}] id={row_id} SKIP (already in SoT)")
            continue

        print(f"[{i+1}/{len(failed)}] id={row_id} | {title_es[:50]}", end=' ... ', flush=True)

        key = normalize(title_es)
        translation = KNOWN_TRANSLATIONS.get(key)

        if not translation:
            # Try with truncated key (first 40 chars)
            for k in KNOWN_TRANSLATIONS:
                if key.startswith(k[:30]) and len(k) > 10:
                    translation = KNOWN_TRANSLATIONS[k]
                    break

        if not translation:
            still_failed.append(entry)
            print(f"✗ no translation")
            continue

        search_title, dir_fragment = translation
        omdb_data = search_omdb_title(search_title)
        time.sleep(RATE_LIMIT)

        if not omdb_data or not omdb_data.get('imdbID'):
            still_failed.append(entry)
            print(f"✗ OMDB miss for '{search_title}'")
            continue

        # Verify director if we have a fragment
        omdb_director = omdb_data.get('Director', '').lower()
        if dir_fragment and dir_fragment not in omdb_director:
            # Queue as fuzzy rather than auto-confirm
            fuzzy.append({
                **entry,
                'candidate_imdb_id': omdb_data['imdbID'],
                'candidate_title': omdb_data.get('Title'),
                'match_type': 'mcp_pass4_director_mismatch',
            })
            print(f"? dir mismatch: {omdb_data.get('Title')} ({omdb_data['imdbID']}) expected dir~'{dir_fragment}' got '{omdb_director[:30]}'")
            continue

        # Confirm
        cat_id = int(row_id) if str(row_id).isdigit() else None
        update_movie(
            title_es, omdb_data,
            match_type='mcp_pass4_translation',
            catalogue=CATALOGUE_NAME,
            catalogue_id=cat_id,
            page_number=None,
        )
        newly_confirmed.append({
            'id': row_id, 'title_spanish': title_es,
            'imdb_id': omdb_data['imdbID'],
            'matched_title': omdb_data.get('Title'),
            'searched_as': search_title,
        })
        print(f"✓ {omdb_data.get('Title')} ({omdb_data['imdbID']})")

    # Save updated pending
    updated = {
        'summary': {
            'newly_confirmed': len(newly_confirmed),
            'fuzzy_review': len(fuzzy),
            'failed_no_match': len(still_failed),
        },
        'fuzzy_candidates': fuzzy,
        'failed_no_match': still_failed,
    }
    with open(PENDING_PATH, 'w', encoding='utf-8') as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)

    print(f"\n=== PASS 4 RESULTS ===")
    print(f"  Newly confirmed : {len(newly_confirmed)}")
    print(f"  Fuzzy (review)  : {len(fuzzy)}")
    print(f"  Still failed    : {len(still_failed)}")


if __name__ == '__main__':
    main()
