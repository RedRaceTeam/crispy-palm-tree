# data/drivers.py
# Все 33 пилота IndyCar 2026

DRIVERS = {
    # ===== CHIP GANASSI RACING =====
    "PAL": {
        "name": "Alex Palou",
        "team": "Chip Ganassi Racing",
        "number": 10,
        "rarity": "ULTIMATE",
        "price": 1200,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/AlexPalou.png"
    },
    "DIX": {
        "name": "Scott Dixon",
        "team": "Chip Ganassi Racing",
        "number": 9,
        "rarity": "ULTIMATE",
        "price": 1000,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ScottDixon.png"
    },
    "SIM": {
        "name": "Kyffin Simpson",
        "team": "Chip Ganassi Racing",
        "number": 8,
        "rarity": "REGULAR",
        "price": 80,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/KyffinSimpson.png"
    },
    
    # ===== TEAM PENSKE =====
    "NEW": {
        "name": "Josef Newgarden",
        "team": "Team Penske",
        "number": 2,
        "rarity": "LEGENDARY",
        "price": 850,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/JosefNewgarden.png"
    },
    "MCL": {
        "name": "Scott McLaughlin",
        "team": "Team Penske",
        "number": 3,
        "rarity": "EXCLUSIVE",
        "price": 520,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ScottMcLaughlin.png"
    },
    "MAL": {
        "name": "David Malukas",
        "team": "Team Penske",
        "number": 12,
        "rarity": "LEGENDARY",
        "price": 700,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/DavidMalukas.png"
    },
    
    # ===== ANDRETTI GLOBAL =====
    "KIR": {
        "name": "Kyle Kirkwood",
        "team": "Andretti Global",
        "number": 27,
        "rarity": "LEGENDARY",
        "price": 800,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/KyleKirkwood.png"
    },
    "ERI": {
        "name": "Marcus Ericsson",
        "team": "Andretti Global",
        "number": 28,
        "rarity": "RARE",
        "price": 380,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/MarcusEricsson.png"
    },
    "POW": {
        "name": "Will Power",
        "team": "Andretti Global",
        "number": 26,
        "rarity": "ULTIMATE",
        "price": 950,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/WillPower.png"
    },
    
    # ===== ARROW MCLAREN =====
    "OWA": {
        "name": "Pato O'Ward",
        "team": "Arrow McLaren",
        "number": 5,
        "rarity": "LEGENDARY",
        "price": 750,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/PatoOWard.png"
    },
    "LUN": {
        "name": "Christian Lundgaard",
        "team": "Arrow McLaren",
        "number": 7,
        "rarity": "EXCLUSIVE",
        "price": 600,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ChristianLundgaard.png"
    },
    "SIE": {
        "name": "Nolan Siegel",
        "team": "Arrow McLaren",
        "number": 6,
        "rarity": "REGULAR",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/NolanSiegel.png"
    },
    "HUN": {
        "name": "Ryan Hunter-Reay",
        "team": "Arrow McLaren",
        "number": 31,
        "rarity": "EXCLUSIVE",
        "price": 450,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/RyanHunterReay.png"
    },
    
    # ===== MEYER SHANK RACING =====
    "ROS": {
        "name": "Felix Rosenqvist",
        "team": "Meyer Shank Racing",
        "number": 60,
        "rarity": "EXCLUSIVE",
        "price": 550,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/FelixRosenqvist.png"
    },
    "ARM": {
        "name": "Marcus Armstrong",
        "team": "Meyer Shank Racing",
        "number": 66,
        "rarity": "RARE",
        "price": 300,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/MarcusArmstrong.png"
    },
    "CAS": {
        "name": "Helio Castroneves",
        "team": "Meyer Shank Racing",
        "number": 6,
        "rarity": "INDY_EDITION",
        "price": 1000,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/HelioCastroneves.png"
    },
    
    # ===== RAHAL LETTERMAN LANIGAN =====
    "RAH": {
        "name": "Graham Rahal",
        "team": "Rahal Letterman Lanigan Racing",
        "number": 15,
        "rarity": "RARE",
        "price": 250,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/GrahamRahal.png"
    },
    "FOS": {
        "name": "Louis Foster",
        "team": "Rahal Letterman Lanigan Racing",
        "number": 45,
        "rarity": "REGULAR",
        "price": 120,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/LouisFoster.png"
    },
    "SCH": {
        "name": "Mick Schumacher",
        "team": "Rahal Letterman Lanigan Racing",
        "number": 47,
        "rarity": "EXCLUSIVE",
        "price": 450,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/MickSchumacher.png"
    },
    "SAT": {
        "name": "Takuma Sato",
        "team": "Rahal Letterman Lanigan Racing",
        "number": 75,
        "rarity": "INDY_EDITION",
        "price": 600,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/TakumaSato.png"
    },
    
    # ===== ED CARPENTER RACING =====
    "ROSS": {
        "name": "Alexander Rossi",
        "team": "Ed Carpenter Racing",
        "number": 20,
        "rarity": "EXCLUSIVE",
        "price": 400,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/AlexanderRossi.png"
    },
    "RAS": {
        "name": "Christian Rasmussen",
        "team": "Ed Carpenter Racing",
        "number": 21,
        "rarity": "REGULAR",
        "price": 90,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ChristianRasmussen.png"
    },
    "CAR": {
        "name": "Ed Carpenter",
        "team": "Ed Carpenter Racing",
        "number": 33,
        "rarity": "RARE",
        "price": 200,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/EdCarpenter.png"
    },
    
    # ===== A.J. FOYT ENTERPRISES =====
    "FER": {
        "name": "Santino Ferrucci",
        "team": "A.J. Foyt Enterprises",
        "number": 14,
        "rarity": "RARE",
        "price": 180,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/SantinoFerrucci.png"
    },
    "COL": {
        "name": "Caio Collet",
        "team": "A.J. Foyt Enterprises",
        "number": 4,
        "rarity": "REGULAR",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/CaioCollet.png"
    },
    
    # ===== JUNCOS HOLLINGER RACING =====
    "VEE": {
        "name": "Rinus VeeKay",
        "team": "Juncos Hollinger Racing",
        "number": 76,
        "rarity": "RARE",
        "price": 350,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/RinusVeeKay.png"
    },
    "ROB": {
        "name": "Sting Ray Robb",
        "team": "Juncos Hollinger Racing",
        "number": 77,
        "rarity": "REGULAR",
        "price": 80,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/StingRayRobb.png"
    },
    
    # ===== DALE COYNE RACING =====
    "GRO": {
        "name": "Romain Grosjean",
        "team": "Dale Coyne Racing",
        "number": 18,
        "rarity": "RARE",
        "price": 280,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/RomainGrosjean.png"
    },
    "HAU": {
        "name": "Dennis Hauger",
        "team": "Dale Coyne Racing",
        "number": 19,
        "rarity": "REGULAR",
        "price": 120,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/DennisHauger.png"
    },
    
    # ===== PREMA RACING =====
    "ILO": {
        "name": "Callum Ilott",
        "team": "PREMA Racing",
        "number": 90,
        "rarity": "RARE",
        "price": 200,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/CallumIlott.png"
    },
    "SHW": {
        "name": "Robert Shwartzman",
        "team": "PREMA Racing",
        "number": 83,
        "rarity": "RARE",
        "price": 180,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/RobertShwartzman.png"
    },
    
    # ===== DREYER & REINBOLD =====
    "DAL": {
        "name": "Conor Daly",
        "team": "Dreyer & Reinbold Racing",
        "number": 23,
        "rarity": "RARE",
        "price": 220,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ConorDaly.png"
    },
    "HAR": {
        "name": "Jack Harvey",
        "team": "Dreyer & Reinbold Racing",
        "number": 24,
        "rarity": "REGULAR",
        "price": 150,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/JackHarvey.png"
    },
    
    # ===== HMD MOTORSPORTS =====
    "LEG": {
        "name": "Katherine Legge",
        "team": "HMD Motorsports",
        "number": 11,
        "rarity": "REGULAR",
        "price": 80,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/KatherineLegge.png"
    },
    
    # ===== ABEL MOTORSPORTS =====
    "ABE": {
        "name": "Jacob Abel",
        "team": "Abel Motorsports",
        "number": 51,
        "rarity": "REGULAR",
        "price": 90,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/JacobAbel.png"
    }
}
