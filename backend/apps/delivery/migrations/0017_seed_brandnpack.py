"""Seed the BrandnPack delivery partner and its rate card (Plan-39).

The 55 rows are the partner's own Word doc ("Lagos State Delivery Price List &
Location for Toke Ogudu", received 2026-08-19), verbatim. Eight rows arrived
unpriced or range-priced (all of Badagry and Epe; Eti-Osa East and Lekki LCDA) —
Hammed's ruling was to import them INACTIVE with a NULL price, so they sit in the
partner portal badged "needs a price" and never reach checkout until BrandnPack
sets a real figure.

The portal login is created with an UNUSABLE password and a placeholder email:
staff must set the real email + password on the admin partners page before sharing
the portal link — `has_password` on that page is the tell. The placeholder is
@tokecosmetics.com so it can never collide with (or mail) a real BrandnPack inbox.

LGA names are mapped onto the ng_regions fixture spellings via ALIASES; an
unmatched name raises and fails the migration LOUDLY — silently dropping a zone
would surface weeks later as "why does checkout never offer my LGA?".
"""
import secrets

from django.contrib.auth.hashers import make_password
from django.db import migrations

PARTNER_CODE = "brandnpack"
PARTNER_NAME = "BrandnPack"
PLACEHOLDER_EMAIL = "partner-brandnpack@tokecosmetics.com"

# Doc spelling -> ng_regions.json fixture spelling, where they differ.
ALIASES = {
    "Eti-Osa": "Eti Osa",
    "Surulere": "Surulere Lagos State",
}

# (lga, lcda, areas_covered, dispatch_zone, price | None, is_active)
ZONES = [
    ("Agege", "Agege Central", "Pen Cinema, Agege Market, Station Road", "Zone 4 - West Mainland", "4000", True),
    ("Agege", "Orile Agege LCDA", "Orile Agege, Dopemu", "Zone 4 - West Mainland", "4000", True),
    ("Ajeromi-Ifelodun", "Ajeromi Central", "Ajegunle, Boundary Market", "Zone 5 - Maritime Corridor", "5500", True),
    ("Ajeromi-Ifelodun", "Ifelodun LCDA", "Layeni, Amukoko, Mosafejo", "Zone 5 - Maritime Corridor", "5500", True),
    ("Alimosho", "Agbado/Oke-Odo LCDA", "Iyana-Ipaja, Abule Egba, Meiran", "Zone 4 - West Mainland", "5000", True),
    ("Alimosho", "Ayobo-Ipaja LCDA", "Ipaja, Ayobo, Baruwa", "Zone 4 - West Mainland", "5000", True),
    ("Alimosho", "Egbe-Idimu LCDA", "Idimu, Egbe, Pipeline", "Zone 4 - West Mainland", "5000", True),
    ("Alimosho", "Igando-Ikotun LCDA", "Ikotun, Igando, General Hospital Axis", "Zone 4 - West Mainland", "5000", True),
    ("Alimosho", "Mosan-Okunola LCDA", "Egbeda, Gowon Estate, Mosan", "Zone 4 - West Mainland", "5000", True),
    ("Amuwo-Odofin", "Amuwo-Odofin Central", "Festac Town, Mile 2", "Zone 5 - Maritime Corridor", "6500", True),
    ("Amuwo-Odofin", "Oriade LCDA", "Satellite Town, Kirikiri, Abule Ado", "Zone 5 - Maritime Corridor", "6500", True),
    ("Apapa", "Apapa Central", "Apapa Wharf, Port Area, Marine Road", "Zone 5 - Maritime Corridor", "5000", True),
    ("Apapa", "Apapa Iganmu LCDA", "Iganmu Industrial Area, Ijora Badia", "Zone 5 - Maritime Corridor", "5000", True),
    ("Badagry", "Badagry Central", "Badagry Town, Heritage Museum Axis", "Zone 5 - Maritime Corridor", None, False),
    ("Badagry", "Badagry West LCDA", "Seme Border, Krake", "Zone 5 - Maritime Corridor", None, False),
    ("Badagry", "Olorunda LCDA", "Aradagun, Iworo", "Zone 5 - Maritime Corridor", None, False),
    ("Epe", "Epe Central", "Epe Town, Marina Waterfront", "Zone 2 - Island Outer", None, False),
    ("Epe", "Eredo LCDA", "Eredo, Noforija, Mojoda", "Zone 2 - Island Outer", None, False),
    ("Epe", "Ikosi-Ejinrin LCDA", "Agbowa-Ikosi, Ejinrin", "Zone 2 - Island Outer", None, False),
    # Range-priced in the doc ("4,000-6,500") — needs a single figure from the partner.
    ("Eti-Osa", "Eti-Osa East LCDA", "Lekki Phase 1, Ikate, Chevron, Ajah, Sangotedo", "Zone 1 & 2 - Island Core/Outer", None, False),
    ("Eti-Osa", "Ikoyi-Obalende LCDA", "Ikoyi (Old GRA, Banana Island), Obalende", "Zone 1 - Island Core", "4000", True),
    ("Eti-Osa", "Iru-Victoria Island LCDA", "Victoria Island, Oniru", "Zone 1 - Island Core", "4000", True),
    ("Ibeju-Lekki", "Ibeju-Lekki Central", "Awoyaya, Akodo", "Zone 2 - Island Outer", "6500", True),
    # Range-priced in the doc ("7,000-12,000").
    ("Ibeju-Lekki", "Lekki LCDA", "Abijo, Bogije, Lakowe, Eleko, Dangote FTZ", "Zone 2 - Island Outer", None, False),
    ("Ifako-Ijaiye", "Ifako-Ijaiye Central", "Ifako, Ogba, College Road", "Zone 4 - West Mainland", "4500", True),
    ("Ifako-Ijaiye", "Ojokoro LCDA", "Ojokoro, Ijaiye, Jankara", "Zone 4 - West Mainland", "4500", True),
    ("Ikeja", "Ikeja Central", "Alausa (Secretariat), Allen Avenue, Computer Village, GRA", "Zone 3 - Central Mainland", "3500", True),
    ("Ikeja", "Ojodu LCDA", "Ojodu, Berger, Omole Phase 1 & 2", "Zone 3 - Central Mainland", "4000", True),
    ("Ikeja", "Onigbongbo LCDA", "Maryland, Anthony, Onigbongbo", "Zone 3 - Central Mainland", "3500", True),
    ("Ikorodu", "Igbogbo-Baiyeku LCDA", "Igbogbo, Baiyeku, Offin", "Zone 6 - Northeast Suburbs", "5000", True),
    ("Ikorodu", "Ijede LCDA", "Ijede, Egbin Power Station Area", "Zone 6 - Northeast Suburbs", "5000", True),
    ("Ikorodu", "Ikorodu Central", "Ikorodu Town, Garage, Benson", "Zone 6 - Northeast Suburbs", "3000", True),
    ("Ikorodu", "Ikorodu North LCDA", "Odogunyan, Maya, Isiwu", "Zone 6 - Northeast Suburbs", "5500", True),
    ("Ikorodu", "Ikorodu West LCDA", "Ogolonto, Agric, Majidun", "Zone 6 - Northeast Suburbs", "5000", True),
    ("Ikorodu", "Imota LCDA", "Imota, Rice Mill Axis", "Zone 6 - Northeast Suburbs", "5500", True),
    ("Kosofe", "Agboyi-Ketu LCDA", "Agboyi, Ketu, Mile 12 Market", "Zone 3 - Central Mainland", "3000", True),
    ("Kosofe", "Ikosi-Isheri LCDA", "Ikosi, Isheri North, Magodo Phase 1 & 2", "Zone 3 - Central Mainland", "4000", True),
    ("Kosofe", "Kosofe Central", "Gbagada, Ojota, Oworonshoki", "Zone 3 - Central Mainland", "4000", True),
    ("Lagos Island", "Lagos Island East LCDA", "Isale Eko, Idumota, Sangrouse", "Zone 1 - Island Core", "4500", True),
    ("Lagos Island", "Lagos Island West", "Marina, Broad Street, Balogun Market", "Zone 1 - Island Core", "4500", True),
    ("Lagos Mainland", "Lagos Mainland Central", "Ebute Metta (East/West), Oyingbo Market", "Zone 3 - Central Mainland", "4500", True),
    ("Lagos Mainland", "Yaba LCDA", "Sabo, Akoka, UNILAG, Onike, Fola Agoro", "Zone 3 - Central Mainland", "4000", True),
    ("Mushin", "Mushin Central", "Mushin Market, Palm Avenue", "Zone 3 - Central Mainland", "4000", True),
    ("Mushin", "Odi Olowo-Ojuwoye LCDA", "Ilupeju, Odi Olowo", "Zone 3 - Central Mainland", "4000", True),
    ("Ojo", "Iba LCDA", "Iba Town, LASU Main Campus Axis", "Zone 5 - Maritime Corridor", "7000", True),
    ("Ojo", "Ojo Central", "Ojo Town, Alaba International Market", "Zone 5 - Maritime Corridor", "7000", True),
    ("Ojo", "Oto-Awori LCDA", "Oto-Awori, Ijanikin", "Zone 5 - Maritime Corridor", "7000", True),
    ("Oshodi-Isolo", "Ejigbo LCDA", "Ejigbo, Jakande Estate", "Zone 4 - West Mainland", "4500", True),
    ("Oshodi-Isolo", "Isolo LCDA", "Isolo, Ajao Estate, Oke-Afa", "Zone 4 - West Mainland", "4000", True),
    ("Oshodi-Isolo", "Oshodi Central", "Oshodi Interchange, Mafoluku", "Zone 4 - West Mainland", "4000", True),
    ("Shomolu", "Bariga LCDA", "Bariga, Pedro, Akoka Boundary", "Zone 3 - Central Mainland", "4000", True),
    ("Shomolu", "Shomolu Central", "Shomolu, Palmgrove, Onipanu", "Zone 3 - Central Mainland", "4000", True),
    ("Surulere", "Coker-Aguda LCDA", "Aguda, Coker, Orile Surulere", "Zone 3 - Central Mainland", "4000", True),
    ("Surulere", "Itire-Ikate LCDA", "Itire, Ijesha, Ikate-Surulere", "Zone 3 - Central Mainland", "4500", True),
    ("Surulere", "Surulere Central", "National Stadium, Bode Thomas, Ojuelegba", "Zone 3 - Central Mainland", "4000", True),
]

# Same alphabet as accounts.models.TOKE_ID_ALPHABET — inlined because a migration
# must not import live app code (the constant could move; this file must not).
_TOKE_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def seed(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Region = apps.get_model("core", "Region")
    DeliveryPartner = apps.get_model("delivery", "DeliveryPartner")
    PartnerZone = apps.get_model("delivery", "PartnerZone")

    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos")
    lgas = {r.name: r for r in Region.objects.filter(parent=lagos, level="area")}

    missing = sorted(
        {ALIASES.get(lga, lga) for lga, *_ in ZONES} - set(lgas)
    )
    if missing:  # fail LOUDLY — see the module docstring
        raise RuntimeError(f"BrandnPack seed: no Lagos LGA region named {missing}")

    toke_id = "TK-" + "".join(secrets.choice(_TOKE_ID_ALPHABET) for _ in range(6))
    while User.objects.filter(toke_id=toke_id).exists():
        toke_id = "TK-" + "".join(secrets.choice(_TOKE_ID_ALPHABET) for _ in range(6))
    user, _ = User.objects.get_or_create(
        email=PLACEHOLDER_EMAIL,
        defaults={
            "first_name": "BrandnPack",
            "last_name": "Logistics",
            "password": make_password(None),  # unusable until staff set one
            "toke_id": toke_id,
        },
    )
    partner, _ = DeliveryPartner.objects.get_or_create(
        code=PARTNER_CODE, defaults={"name": PARTNER_NAME, "user": user},
    )

    for lga, lcda, areas, zone, price, active in ZONES:
        PartnerZone.objects.get_or_create(
            partner=partner,
            lga_region=lgas[ALIASES.get(lga, lga)],
            lcda_name=lcda,
            defaults={
                "areas_covered": areas,
                "dispatch_zone": zone,
                "price": price,
                "is_active": active,
            },
        )


def unseed(apps, schema_editor):
    DeliveryPartner = apps.get_model("delivery", "DeliveryPartner")
    User = apps.get_model("accounts", "User")
    DeliveryPartner.objects.filter(code=PARTNER_CODE).delete()  # zones cascade
    User.objects.filter(email=PLACEHOLDER_EMAIL).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0016_deliverypartner_partnerzone"),
        ("accounts", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
