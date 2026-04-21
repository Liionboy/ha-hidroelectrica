<h1 align="center">
  Hidroelectrica România (iHidro)
</h1>

<p align="center">
  <a href="https://github.com/Liionboy/ha-hidroelectrica/releases"><img src="https://img.shields.io/github/v/release/Liionboy/ha-hidroelectrica?style=flat-square" alt="Release"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg" alt="HACS"></a>
  <a href="https://github.com/Liionboy/ha-hidroelectrica/issues"><img src="https://img.shields.io/github/issues/Liionboy/ha-hidroelectrica" alt="Issues"></a>
  <a href="https://github.com/Liionboy/ha-hidroelectrica/pulls"><img src="https://img.shields.io/github/issues-pr/Liionboy/ha-hidroelectrica" alt="Pull Requests"></a>
</p>

<p align="center">
  Integrare <b>neoficială</b> pentru platforma <a href="https://ihidro.ro">iHidro (Hidroelectrica)</a>, destinată aducerii datelor dumneavoastră de facturare și consum direct în Home Assistant. Construită cu suport extins și un API optimizat, consumând cu mult mai puține resurse și minimizând riscul de ban, această componentă este pregătită pentru cele mai complexe rețele casnice și conturi cu multiple locuri de consum.
</p>

---

## ✨ Caracteristici
- **Senzori de Facturare Avansați**: Sold curent detaliat, informații despre ultima factură și termenele de plată.
- **Senzori de Energie & Index (Prosumatori Inclus)**: Preluare inteligentă a indexului de consum (1.8.0) și a indexului de injecție (2.8.0) pentru rețea.
- **Support Complet Multi-Account (Multi-POD)**: Dețineți mai multe apartamente sau case pe același cont? Nicio problemă. Integrarea va detecta automat și va crea un *Device (Dispozitiv)* independent pentru fiecare loc de consum.
- **Optimizări de Apelare**: Tehnologie „Heavy/Light Update”. Majoritatea refresh-urilor cer doar datele minimale. O dată pe zi, se trage un volum întreg „greu” pentru a economisi trafic și pentru a nu atrage sancțiuni din partea serverelor Hidroelectrica.
- **Setări Dinamice post-configurare**: Poți filtra/adăuga/elimina punctele de consum (conturile) aduse direct din meniul de **Configure** al integrării din Home Assistant.

## 🚀 Instalare

### Metoda 1: Instalare folosind HACS (Recomandată)
Aceasta este cea mai simplă metodă și vă permite să primiți update-uri viitoare automat.
1. Deschideți HACS în Home Assistant.
2. Selectați **Integrations**.
3. Dați click pe cele 3 puncte (sus-dreapta) și alegeți **Custom repositories**.
4. La **Repository**, adăugați link-ul acestui depozit: `https://github.com/Liionboy/ha-hidroelectrica`. La **Category**, alegeți `Integration`.
5. Apăsați pe **Add** și apoi instalați integrarea nou adăugată.
6. **Reporniți (Restart) Home Assistant.**

### Metoda 2: Instalare Manuală
1. Copiați întregul folder `custom_components/hidroelectrica` din acest repository în folderul `config/custom_components/` al instanței dumneavoastră Home Assistant.
2. **Reporniți Home Assistant.**

## ⚙️ Configurare

1. Mergeți la **Settings** -> **Devices & Services**.
2. Apăsați pe butonul **Add Integration**.
3. Căutați **Hidroelectrica România (iHidro)**.
4. Introduceți adresa de e-mail (username-ul) și parola setate pe platforma iHidro.ro.
5. Integrarea vă va detecta automat locurile de consum și le va organiza frumos în interfața Home Assistant.

> [!TIP]
> **Modificarea Conturilor Urmărite**: Dacă doriți să ascundeți un anumit cont/apartament, mergeți pe pagina integrării, dați click pe **Configure** și debifați din listă contul pe care nu mai doriți să-l actualizați.

## 🧩 Card Lovelace inclus (v1)
- Fișier: `custom_components/hidroelectrica/www/hidroelectrica-card.js`
- Resource: `/local/hidroelectrica-card.js` (după copiere în `/config/www/`)
- Tip card: `custom:hidroelectrica-card`

## 🔌 Senzori Incluși
Se creează câte un grup de senzori per loc de consum (Dispozitiv / Device):
* `sensor.sold_curent` (cu atribute detaliate pentru facturile neînchise)
* `sensor.ultima_factura`
* `sensor.index_consum_1_8_0` (Energie din rețea)
* `sensor.index_injectie_2_8_0` (Energie în rețea - vizibil dacă există profil de Prosumator)

## 🐛 Boli cunoscute și Limitări
Deoarece componenta citește o platformă nestandardizată, orice schimbare directă în site-ul / aplicația mobilă oficială "iHidro" ar putea opri temporar funcționalitatea senzorilor (până la actualizarea codului de analiză). Vă rugăm să folosiți tab-ul de **Issues** pentru a sesiza eventualele erori noi prin publicarea mesajului de pe consolă sau logbook.

---
**Disclaimer:** *Această integrare dezvoltată open-source nu este afiliată sau susținută oficial de S.P.E.E.H Hidroelectrica S.A. Utilizarea este pe propria răspundere, neexistând o garanție asupra stabilității pe termen lung a platformei țintă (iHidro.ro).*
