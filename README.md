# Hidroelectrica România (iHidro) pentru Home Assistant

Integrare neoficială pentru platforma iHidro (Hidroelectrica), dezvoltată de la zero.

## Caracteristici
- **Senzori de Facturare**: Sold curent, valoarea ultimei facturi, data scadenței.
- **Senzori de Energie**: Index consum (1.8.0) și Index injecție (2.8.0) pentru prosumatori.
- **Suport Multi-POD**: Dacă aveți mai multe puncte de consum, integrarea va crea dispozitive separate pentru fiecare.
- **Actualizare la 1 oră**: Pentru a asigura date proaspete fără a supraîncărca serverele.
- **Limba Română**: Toate entitățile și interfețele sunt în limba română.

## Instalare Manuală
1. Copiați folderul `custom_components/hidroelectrica` în folderul `config/custom_components/` al instanței dumneavoastră Home Assistant.
2. Reporniți Home Assistant.
3. Mergeți la **Setări** -> **Dispozitive și Servicii** -> **Adaugă Integrare**.
4. Căutați **Hidroelectrica România (iHidro)** și introduceți datele de autentificare.

## Senzori Incluși
- `sensor.sold_curent`: Soldul total de plată (poate fi negativ dacă aveți credit).
- `sensor.ultima_factura`: Valoarea celei mai recente facturi emise.
- `sensor.index_consum_1_8_0`: Indexul de energie activă consumată (kWh).
- `sensor.index_injectie_2_8_0`: Indexul de energie activă injectată în rețea (kWh - doar pentru prosumatori).

## Disclaimer
Această integrare nu este afiliată sau susținută de Hidroelectrica SA. Utilizați pe propria răspundere.
