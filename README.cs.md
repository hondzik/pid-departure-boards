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

## Služby

| Služba | K čemu |
|---|---|
| `pid_departure_boards.refresh` | Okamžitá obnova — všechny zastávky, nebo jen zadané senzory. |
| `pid_departure_boards.get_departures` | Vrátí odjezdy (a oznámení) jako odpověď. Zadejte buď `entity_id` senzoru, nebo GTFS `stop_id`; `routes` a `limit` jsou volitelné přepisy. |

## Poznámky

- Zpoždění je známé jen tehdy, když vozidlo hlásí polohu; jinak se použije plánovaný čas.
- Seznam zastávek se stáhne jednou a ukládá se na 7 dní.
- Lovelace karta je v samostatném repozitáři `pid-departure-boards-ui`.
