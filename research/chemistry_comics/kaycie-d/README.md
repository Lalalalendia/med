# Kaycie D. — Elements: Experiments in Character Design

## Correction of attribution

The supplied character cards with chemical elements **24–35**, from Chromium (Cr) to Bromine (Br), belong to **Kaycie D.** (Kaycie Dunlap), not to Katie Brookoff / Katie B. Cartoons. The 28-item **Science Pun Cartoons** archive in PR #116 is a different project. Do not merge the two catalogs.

The correct work is **Elements — Experiments in Character Design** (2011–2017), an illustrated personification of the periodic table. The original set of 72 characters was completed in spring 2011, 40 more in November 2011, and the final six (113–118) in 2017, totaling **118**.

## Verified artist sources

- Original: https://kcd-elements.tumblr.com/
- Project history: https://kcd-elements.tumblr.com/about
- Author's terms: https://kcd-elements.tumblr.com/tou
- Official shop (118 illustrations, black-and-white coloring-book PDF): https://kcdstudios-shop.fourthwall.com/products/elements-coloring-book-pdf
- Example individual art: https://www.inprnt.com/gallery/kcdstudios/elements-chromium/

The artist sells the complete 118-image set in **black-and-white** line-art form; do not describe that product as a full-color card set. Her original cards may be viewed in public previews and separate paid flashcard products.

## Image in the request

| Z | Symbol | Element |
|--:|:--|:--|
| 24 | Cr | Chromium |
| 25 | Mn | Manganese |
| 26 | Fe | Iron |
| 27 | Co | Cobalt |
| 28 | Ni | Nickel |
| 29 | Cu | Copper |
| 30 | Zn | Zinc |
| 31 | Ga | Gallium |
| 32 | Ge | Germanium |
| 33 | As | Arsenic |
| 34 | Se | Selenium |
| 35 | Br | Bromine |

## Source/license boundary

The artist's usage policy (2023) bars **editing images**, **mass digital publication**, and **uses of the artwork in AI-related technology** without permission; it also requests proper credit and a link when posting. Therefore this repo stores only links and bibliographic metadata. Do **not** scrape/paywall-bypass, reproduce all 118 images, build a translated derived card deck via AI, or publish the source artwork as a GitHub artifact without first obtaining the appropriate permission/license.

The user wants personal learning materials. If a licensed source file is provided later, verify the actual license before extracting or transforming the art. A clean-room, original educational character system can be designed separately without copying these drawings.

## Scope

This is a correction and source record only; **no original artwork is collected in med**. No deployment or migration.

## Private-use permission and workflow

The project owner states that the artist has given individual permission for **personal, non-public use**, including comics and related material. This is narrower than a grant to publish original artwork on public digital platforms. The original source images and translations must remain in the owner's private storage. Individual permission is user-provided information and is not a public license for other repository visitors.

The previous generic usage-boundary warning must not be interpreted as an unconditional ban on the owner's private collection. The artwork itself is absent from this public repository.

### Source availability

The artist confirms there are 118 characters, but the public Tumblr landing page shows a limited selection, with the remainder available through separate products. A permission grant does not itself make the original PDF bytes available. Do not mislabel a partial 12-image or 28-image dataset as the complete 118.

### Local importer

Install \`Pillow\` and \`PyMuPDF\`, then run:

\`\`\`sh
python tools/chemistry_comics/import_kaycie_private.py --source /private/kaycie-elements.pdf --output /private/elements-reader --expect-full
\`\`\`

For numbered image files, use \`--source /private/cards\` with image filenames beginning with the atomic number such as \`024-chromium.png\`. For a PDF with title/extra pages, use \`--first-page\`, \`--start-element\`, and \`--count\` as appropriate; verify the page-to-element mapping manually. The tool refuses to mark an incomplete collection as full. Only private local files are read; the script never downloads images or sends them to GitHub Actions. The CI tests use generated blank synthetic images.

A personal-use pilot for the user-supplied montage was prepared separately: 12 cards corresponding to elements 24–35, original pictures preserved, Russian translations/chemical comments outside each picture. The ZIP is in the owner's private Google Drive, **not the repo**.
