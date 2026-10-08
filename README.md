# SEO Updates — GitHub Pages

Website ringan untuk memantau update SEO, Google, AI Search, Technical SEO, dan Ads.

## Sources
- Search Engine Journal
- Google Search Central
- Search Engine Roundtable
- Search Engine Land

Search Engine Land memakai fallback otomatis jika endpoint RSS gagal:
1. RSS utama
2. halaman Latest Posts Search Engine Land
3. Google News RSS yang dibatasi ke `site:searchengineland.com`

Workflow berjalan otomatis setiap 30 menit dan dapat dijalankan manual melalui **Actions → Update SEO Feed → Run workflow**.

Jika suatu sumber gagal, `data.json` menyimpan status, metode, jumlah artikel, dan error agar mudah didiagnosis. Workflow tidak akan menimpa feed dengan dataset kosong total.
