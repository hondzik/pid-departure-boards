# PID Departure Boards → Home Assistant

[English](README.md)

[![GitHub Release](https://img.shields.io/github/release/hondzik/pid-departure-boards.svg?style=for-the-badge)](https://github.com/hondzik/pid-departure-boards/releases)
[![License](https://img.shields.io/github/license/hondzik/pid-departure-boards.svg?style=for-the-badge)](LICENSE)
[![Project Maintenance](https://img.shields.io/badge/maintainer-hondzik-blue.svg?style=for-the-badge)](https://github.com/hondzik)
![Github](https://img.shields.io/github/followers/hondzik.svg?style=for-the-badge)
[![GitHub Activity](https://img.shields.io/github/last-commit/hondzik/pid-departure-boards?style=for-the-badge)](https://github.com/hondzik/pid-departure-boards/commits/main)

## Popis

Home Assistant integrace, která zobrazuje odjezdy Pražské integrované dopravy (PID)
z vybraných nástupišť. Data pochází z [Golemio API](https://api.golemio.cz/pid/docs/openapi/).

- Jeden **senzor na nástupiště** (zastávka v jednom směru). Stav je čas nejbližšího odjezdu,
  atribut `departures` obsahuje následujících N odjezdů sledovaných linek.
- U každého odjezdu je linka, cíl, plánovaný i predikovaný čas, zpoždění v minutách, typ vozidla,
  příznaky nízkopodlažnosti a klimatizace a příznaky zrušeného spoje, noční, regionální linky
  a náhradní dopravy. Atribut `infotexts` obsahuje aktuální oznámení (výluky).
- Senzor má také atributy `latitude` / `longitude` nástupiště, takže se zobrazí na kartě Mapa
  (viz [Zeměpisná poloha](#zeměpisná-poloha)).
- Služby `pid_departure_boards.refresh` a `pid_departure_boards.get_departures`.
- K zobrazení je k dispozici hotová karta na dashboard — viz [Karta na dashboard](#karta-na-dashboard).

## Instalace

### HACS

[![Otevřít v HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hondzik&repository=pid-departure-boards&category=integration)

1. HACS → Integrace → tři tečky vpravo nahoře → Vlastní repozitáře.
2. Přidat `https://github.com/hondzik/pid-departure-boards` jako typ „Integrace“.
3. Nainstalovat „PID Departure Boards“ a restartovat Home Assistant.

### Ručně

Zkopírovat `custom_components/pid_departure_boards` do `<config>/custom_components/pid_departure_boards`
a restartovat Home Assistant.

## Nastavení

1. Na <https://api.golemio.cz/api-keys> si zdarma vytvořte API klíč.
2. Nastavení → Zařízení a služby → Přidat integraci → „PID Departure Boards“, zadejte klíč.
   Globální nastavení je v možnostech integrace, viz [Možnosti](#možnosti).
3. Na stránce integrace zvolte **Přidat zastávku**:
   - vyhledejte zastávku podle názvu (diakritika není nutná),
   - vyberte nástupiště — každé obsluhuje jeden směr, zobrazuje se jako
     `nástupiště — cíle (linky)`,
   - vyberte sledované linky (prázdný výběr = všechny),
   - nastavte počet odjezdů a případně vlastní interval obnovy pro tuto zastávku.

Linky, počet odjezdů a interval lze později změnit přes **Překonfigurovat**.

## Možnosti

Nastavení → Zařízení a služby → PID Departure Boards → **Konfigurovat**. Platí pro celou
integraci, tedy pro všechny zastávky stejně:

| Možnost | Výchozí | Popis |
|---|---|---|
| Výchozí interval obnovy | 60 s | Jak často se odjezdy obnovují (minimum 30 s — API povoluje 20 požadavků za 8 sekund na jeden klíč). Jednotlivá zastávka ho může přepsat při přidání nebo úpravě. |

Uložením možností se integrace znovu načte.

## Historie (recorder)

Velké atributy `departures` a `infotexts` se do historie Home Assistantu **nikdy neukládají** —
integrace je vyřazuje sama. Zaznamenává se jen stav senzoru (čas nejbližšího odjezdu).

Pokud nechcete ukládat ani ten, vyřaďte senzory v konfiguraci
[recorderu](https://www.home-assistant.io/integrations/recorder/) v `configuration.yaml`. ID entity
vzniká z názvu zastávky, např. `sensor.andel_b`:

```yaml
recorder:
  exclude:
    entities:
      - sensor.andel_b
      - sensor.palmovka_a
```

ID entit nemají předponu s názvem integrace, takže `entity_globs` se hodí jen tehdy, když senzory
přejmenujete na společnou předponu. Už uložená historie se vyřazením nesmaže; smažete ji službou
`recorder.purge_entities`.

## Zeměpisná poloha

Od verze **1.1.0** má senzor každého nástupiště atributy `latitude` a `longitude` (WGS84),
které se při přidání zastávky převezmou ze seznamu zastávek PID. Díky nim lze senzor zobrazit
na kartě **Mapa**.

Zastávky přidané **před verzí 1.1.0 zeměpisnou polohu nemají** a automaticky se nedoplní.
Pro doplnění zastávku odeberte a přidejte znovu (**Přidat zastávku**).

## Karta na dashboard

K zobrazení odjezdů slouží samostatná Lovelace karta
[**pid-departure-boards-ui**](https://github.com/hondzik/pid-departure-boards-ui). Čte senzory
této integrace (Golemio API sama nevolá) a zobrazuje název zastávky, řádek pro každý odjezd s ikonou
vozidla, linkou, cílem, odpočtem / časem odjezdu, zpožděním, ikonami bezbariérovosti a klimatizace,
oznámení a mapu zastávky.

[![Otevřít v HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hondzik&repository=pid-departure-boards-ui&category=plugin)

Nainstalujte ji přes HACS jako repozitář typu **Dashboard** (plugin) a přidejte na dashboard:

```yaml
type: custom:pid-departure-boards-ui-departures-card
entity: sensor.andel_b
```

Všechny možnosti jsou v [README karty](https://github.com/hondzik/pid-departure-boards-ui#readme).

## Služby

| Služba | K čemu |
|---|---|
| `pid_departure_boards.refresh` | Okamžitá obnova — všechny zastávky, nebo jen zadané senzory. |
| `pid_departure_boards.get_departures` | Vrátí odjezdy (a oznámení) jako odpověď. Zadejte buď `entity_id` senzoru, nebo GTFS `stop_id`; `routes` a `limit` jsou volitelné přepisy. |
| `pid_departure_boards.get_route_shapes` | Vrátí trasu (zjednodušenou čáru z bodů `[lon, lat]`) každé sledované linky senzoru ve směru, který nástupiště obsluhuje. Linka bez odjezdu v následujících 4 hodinách trasu nemá (`null`). |
| `pid_departure_boards.get_vehicle_positions` | Vrátí aktuální pozice (s azimutem, zpožděním a stavem) vozidel sledovaných linek, která jedou směrem obsluhovaným nástupištěm. Pozice se cachují asi 5 sekund. |

Služby pro trasu a vozidla jsou určené pro mapu — berou jen `entity_id` senzoru a použijí jeho sledované
linky. Směr se určuje podle nejbližšího odjezdu každé linky z nástupiště; vozidla se k němu přiřazují podle
linky a cíle.

## Poznámky

- Zpoždění je známé jen tehdy, když vozidlo hlásí polohu; jinak se použije plánovaný čas.
- Golemio API občas odpoví HTTP 401 i na platný klíč (například při velké zátěži). Senzory se pak jen na chvíli
  stanou nedostupnými a integrace to zkusí znovu; výzva k novému zadání klíče se zobrazí až tehdy, když chyba trvá
  3 minuty v kuse.
- Seznam zastávek se stáhne jednou a ukládá se na 7 dní.
