# data/drivers.py
# 33 пилота IndyCar 2026

DRIVERS = {
    # ===== CHIP GANASSI RACING (Honda) =====
    "PAL": {
        "name": "Alex Palou",
        "team": "Chip Ganassi Racing",
        "number": 10,
        "rarity": "ULTIMATE",
        "price": 5500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/AlexPalou.png"
    },
    "DIX": {
        "name": "Scott Dixon",
        "team": "Chip Ganassi Racing",
        "number": 9,
        "rarity": "ULTIMATE",
        "price": 4500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ScottDixon.png"
    },
    "SIM": {
        "name": "Kyffin Simpson",
        "team": "Chip Ganassi Racing",
        "number": 8,
        "rarity": "COMMON",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/KyffinSimpson.png"
    },
    
    # ===== TEAM PENSKE (Chevrolet) =====
    "NEW": {
        "name": "Josef Newgarden",
        "team": "Team Penske",
        "number": 2,
        "rarity": "LEGENDARY",
        "price": 3200,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/JosefNewgarden.png"
    },
    "MCL": {
        "name": "Scott McLaughlin",
        "team": "Team Penske",
        "number": 3,
        "rarity": "EPIC",
        "price": 1500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ScottMcLaughlin.png"
    },
    "MAL": {
        "name": "David Malukas",
        "team": "Team Penske",
        "number": 12,
        "rarity": "LEGENDARY",
        "price": 2800,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/DavidMalukas.png"
    },
    
    # ===== ANDRETTI GLOBAL (Honda) =====
    "KIR": {
        "name": "Kyle Kirkwood",
        "team": "Andretti Global",
        "number": 27,
        "rarity": "LEGENDARY",
        "price": 2500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/KyleKirkwood.png"
    },
    "ERI": {
        "name": "Marcus Ericsson",
        "team": "Andretti Global",
        "number": 28,
        "rarity": "RARE",
        "price": 900,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/MarcusEricsson.png"
    },
    "POW": {
        "name": "Will Power",
        "team": "Andretti Global",
        "number": 26,
        "rarity": "ULTIMATE",
        "price": 4000,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/WillPower.png"
    },
    
    # ===== ARROW MCLAREN (Chevrolet) =====
    "OWA": {
        "name": "Pato O'Ward",
        "team": "Arrow McLaren",
        "number": 5,
        "rarity": "LEGENDARY",
        "price": 3000,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/PatoOWard.png"
    },
    "LUN": {
        "name": "Christian Lundgaard",
        "team": "Arrow McLaren",
        "number": 7,
        "rarity": "EPIC",
        "price": 1600,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ChristianLundgaard.png"
    },
    "SIE": {
        "name": "Nolan Siegel",
        "team": "Arrow McLaren",
        "number": 6,
        "rarity": "COMMON",
        "price": 120,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/NolanSiegel.png"
    },
    "HUN": {
        "name": "Ryan Hunter-Reay",
        "team": "Arrow McLaren",
        "number": 31,
        "rarity": "EPIC",
        "price": 1400,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/RyanHunterReay.png"
    },
    
    # ===== MEYER SHANK RACING (Honda) =====
    "ROS": {
        "name": "Felix Rosenqvist",
        "team": "Meyer Shank Racing",
        "number": 60,
        "rarity": "EPIC",
        "price": 1600,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/FelixRosenqvist.png"
    },
    "ARM": {
        "name": "Marcus Armstrong",
        "team": "Meyer Shank Racing",
        "number": 66,
        "rarity": "RARE",
        "price": 600,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/MarcusArmstrong.png"
    },
    "CAS": {
        "name": "Helio Castroneves",
        "team": "Meyer Shank Racing",
        "number": 6,
        "rarity": "INDY_EDITION",
        "price": 3500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/HelioCastroneves.png"
    },
    
    # ===== RAHAL LETTERMAN LANIGAN (Honda) =====
    "RAH": {
        "name": "Graham Rahal",
        "team": "Rahal Letterman Lanigan Racing",
        "number": 15,
        "rarity": "RARE",
        "price": 500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/GrahamRahal.png"
    },
    "FOS": {
        "name": "Louis Foster",
        "team": "Rahal Letterman Lanigan Racing",
        "number": 45,
        "rarity": "COMMON",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/LouisFoster.png"
    },
    "SCH": {
        "name": "Mick Schumacher",
        "team": "Rahal Letterman Lanigan Racing",
        "number": 47,
        "rarity": "EPIC",
        "price": 2000,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/MickSchumacher.png"
    },
    "SAT": {
        "name": "Takuma Sato",
        "team": "Rahal Letterman Lanigan Racing",
        "number": 75,
        "rarity": "INDY_EDITION",
        "price": 2500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/TakumaSato.png"
    },
    
    # ===== ED CARPENTER RACING (Chevrolet) =====
    "ROSS": {
        "name": "Alexander Rossi",
        "team": "Ed Carpenter Racing",
        "number": 20,
        "rarity": "EPIC",
        "price": 1400,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/AlexanderRossi.png"
    },
    "RAS": {
        "name": "Christian Rasmussen",
        "team": "Ed Carpenter Racing",
        "number": 21,
        "rarity": "COMMON",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ChristianRasmussen.png"
    },
    "CAR": {
        "name": "Ed Carpenter",
        "team": "Ed Carpenter Racing",
        "number": 33,
        "rarity": "RARE",
        "price": 400,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/EdCarpenter.png"
    },
    
    # ===== A.J. FOYT ENTERPRISES (Chevrolet) =====
    "FER": {
        "name": "Santino Ferrucci",
        "team": "A.J. Foyt Enterprises",
        "number": 14,
        "rarity": "RARE",
        "price": 450,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/SantinoFerrucci.png"
    },
    "COL": {
        "name": "Caio Collet",
        "team": "A.J. Foyt Enterprises",
        "number": 4,
        "rarity": "COMMON",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/CaioCollet.png"
    },
    
    # ===== JUNCOS HOLLINGER RACING (Chevrolet) =====
    "VEE": {
        "name": "Rinus VeeKay",
        "team": "Juncos Hollinger Racing",
        "number": 76,
        "rarity": "RARE",
        "price": 700,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/RinusVeeKay.png"
    },
    "ROB": {
        "name": "Sting Ray Robb",
        "team": "Juncos Hollinger Racing",
        "number": 77,
        "rarity": "COMMON",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/StingRayRobb.png"
    },
    
    # ===== DALE COYNE RACING (Honda) =====
    "GRO": {
        "name": "Romain Grosjean",
        "team": "Dale Coyne Racing",
        "number": 18,
        "rarity": "RARE",
        "price": 650,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/RomainGrosjean.png"
    },
    "HAU": {
        "name": "Dennis Hauger",
        "team": "Dale Coyne Racing",
        "number": 19,
        "rarity": "COMMON",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/DennisHauger.png"
    },
    
    # ===== PREMA RACING (Chevrolet) =====
    "ILO": {
        "name": "Callum Ilott",
        "team": "PREMA Racing",
        "number": 90,
        "rarity": "RARE",
        "price": 500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/CallumIlott.png"
    },
    "SHW": {
        "name": "Robert Shwartzman",
        "team": "PREMA Racing",
        "number": 83,
        "rarity": "RARE",
        "price": 500,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/RobertShwartzman.png"
    },
    
    # ===== DREYER & REINBOLD (Chevrolet) =====
    "DAL": {
        "name": "Conor Daly",
        "team": "Dreyer & Reinbold Racing",
        "number": 23,
        "rarity": "RARE",
        "price": 400,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/ConorDaly.png"
    },
    "HAR": {
        "name": "Jack Harvey",
        "team": "Dreyer & Reinbold Racing",
        "number": 24,
        "rarity": "COMMON",
        "price": 150,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/JackHarvey.png"
    },
    
    # ===== HMD MOTORSPORTS (Chevrolet) =====
    "LEG": {
        "name": "Katherine Legge",
        "team": "HMD Motorsports",
        "number": 11,
        "rarity": "COMMON",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/KatherineLegge.png"
    },
    
    # ===== ABEL MOTORSPORTS (Chevrolet) =====
    "ABE": {
        "name": "Jacob Abel",
        "team": "Abel Motorsports",
        "number": 51,
        "rarity": "COMMON",
        "price": 100,
        "image": "https://www.indycar.com/-/media/IndyCar/Drivers/IndyCar-Series/Driver-List/JacobAbel.png"
    }
}
