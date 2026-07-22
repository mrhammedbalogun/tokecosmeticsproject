// Generates the homepage's placeholder art (Plan-13 D4) into public/home/.
// Deterministic: same input -> same files. Replace 1:1 with real photography later.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const OUT = join(import.meta.dirname, "..", "public", "home");
const P = { cream: "#FBF9F5", beige: "#F1EAE0", ink: "#1A1A1A",
            green: "#1C7A3E", dark: "#145F30", leaf: "#8CC63F", gold: "#C9A227" };

const grain = `<filter id="g"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.05"/></feComponentTransfer><feComposite operator="over" in2="SourceGraphic"/></filter>`;

function gradientSvg(w, h, c1, c2, blobColor, seedX, seedY) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}">
<defs><linearGradient id="lg" x1="0" y1="0" x2="0.3" y2="1">
<stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/></linearGradient>
<radialGradient id="rg" cx="${seedX}" cy="${seedY}" r="0.6">
<stop offset="0" stop-color="${blobColor}" stop-opacity="0.55"/>
<stop offset="1" stop-color="${blobColor}" stop-opacity="0"/></radialGradient>${grain}</defs>
<rect width="${w}" height="${h}" fill="url(#lg)"/>
<rect width="${w}" height="${h}" fill="url(#rg)"/>
<rect width="${w}" height="${h}" filter="url(#g)" opacity="0.5"/></svg>`;
}

function avatarSvg(initial, bg) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
<circle cx="48" cy="48" r="48" fill="${bg}"/>
<text x="48" y="60" text-anchor="middle" font-family="Georgia, serif" font-size="38" fill="#FBF9F5">${initial}</text></svg>`;
}

mkdirSync(join(OUT, "concerns"), { recursive: true });
mkdirSync(join(OUT, "community"), { recursive: true });
mkdirSync(join(OUT, "avatars"), { recursive: true });

writeFileSync(join(OUT, "hero.svg"), gradientSvg(1920, 1080, P.beige, P.green, P.gold, 0.75, 0.3));
writeFileSync(join(OUT, "story-1.svg"), gradientSvg(900, 1100, P.cream, P.leaf, P.green, 0.4, 0.35));
writeFileSync(join(OUT, "story-2.svg"), gradientSvg(900, 1100, P.beige, P.gold, P.green, 0.6, 0.5));
writeFileSync(join(OUT, "collection-banner.svg"), gradientSvg(1800, 700, P.green, P.dark, P.gold, 0.8, 0.4));
writeFileSync(join(OUT, "education.svg"), gradientSvg(1200, 700, P.cream, P.beige, P.leaf, 0.5, 0.4));

const concerns = ["acne", "hyperpigmentation", "dry-skin", "oily-skin",
                  "sensitive-skin", "eczema", "dark-spots", "uneven-tone"];
concerns.forEach((slug, i) => writeFileSync(
  join(OUT, "concerns", `${slug}.svg`),
  gradientSvg(600, 600, i % 2 ? P.beige : P.cream, i % 3 ? P.green : P.gold,
              i % 2 ? P.leaf : P.green, 0.3 + (i % 4) * 0.15, 0.3 + (i % 3) * 0.2)));

for (let i = 0; i < 6; i++) writeFileSync(
  join(OUT, "community", `post-${i + 1}.svg`),
  gradientSvg(700, i % 2 ? 900 : 700, i % 2 ? P.cream : P.beige,
              [P.green, P.gold, P.leaf, P.dark][i % 4], P.gold, 0.2 + i * 0.12, 0.5));

["A", "T", "Z", "C", "F"].forEach((ch, i) => writeFileSync(
  join(OUT, "avatars", `a${i + 1}.svg`), avatarSvg(ch, [P.green, P.gold, P.dark, P.leaf, P.ink][i])));

console.log("placeholder art written to public/home/");
