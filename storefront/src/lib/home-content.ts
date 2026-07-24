/** Homepage editorial content (Plan-13 D3). This module IS the "CMS" until
 * Plan-19 ships real content models — keep it typed and boring so Plan-19 can
 * swap each export for an API call without touching the section components.
 * Hammed: edit copy freely; image paths point at public/home/ (D4 placeholders). */

export const ANNOUNCEMENTS = [
  "Free delivery in Nigeria on orders over ₦50,000",
  "Worldwide shipping — UK · US · Canada · everywhere",
  "Dermatologist recommended, made for melanin-rich skin",
  "Secure worldwide checkout",
];

export const HERO = {
  eyebrow: "Premium African skincare",
  headline: "Healthy Skin Begins Here.",
  sub: "Science-backed skincare with African botanicals — made for melanin-rich skin, trusted worldwide.",
  image: "/home/hero.svg",
  // "Take Skin Quiz" (design brief) has no route yet — it points at the concerns
  // grid anchor until the quiz exists (future plan).
  ctas: [
    { label: "Shop Now", href: "/products", primary: true },
    { label: "Take Skin Quiz", href: "#skin-concerns", primary: false },
  ],
};

export const SKIN_CONCERNS = [
  { name: "Acne", slug: "acne" }, { name: "Hyperpigmentation", slug: "hyperpigmentation" },
  { name: "Dry Skin", slug: "dry-skin" }, { name: "Oily Skin", slug: "oily-skin" },
  { name: "Sensitive Skin", slug: "sensitive-skin" }, { name: "Eczema", slug: "eczema" },
  { name: "Dark Spots", slug: "dark-spots" }, { name: "Uneven Tone", slug: "uneven-tone" },
].map((c) => ({ ...c, image: `/home/concerns/${c.slug}.svg`, href: `/products?tag=${c.slug}` }));

export const BRAND_STORY = {
  eyebrow: "Our promise",
  title: "Rooted in nature. Proven by science.",
  paragraphs: [
    "Toke Cosmetics blends cold-pressed African botanicals with clinically proven actives — shea from Kano, black soap from Ogun, formulations reviewed by dermatologists.",
    "Every product is made for melanin-rich skin first, and loved by families everywhere: mothers, babies, teens and men alike.",
  ],
  pillars: [
    "Natural ingredients",
    "Science-backed",
    "Made for melanin-rich skin",
    "Trusted worldwide",
  ],
  images: ["/home/story-1.svg", "/home/story-2.svg"],
  cta: { label: "Our story", href: "/page/about" },
};

/** `icon` is a STABLE key into WhyChoose's ICONS map — decoupled from `title` so
 * editing the copy never blanks an icon. If you add an entry, add a matching icon
 * in WhyChoose.tsx (a test asserts every key resolves). */
export const WHY_CHOOSE = [
  { icon: "clipboard-check", title: "Dermatologist approved", body: "Formulations reviewed by skin professionals." },
  { icon: "leaf", title: "Natural ingredients", body: "African botanicals, no parabens or sulphates." },
  { icon: "heart", title: "Cruelty free", body: "Never tested on animals." },
  { icon: "globe", title: "Worldwide shipping", body: "Lagos to London, New York to Nairobi." },
  { icon: "shield", title: "Secure payments", body: "Bank-grade encryption on every order." },
  { icon: "refresh", title: "Money-back promise", body: "14-day returns, no questions asked." },
] as const;

export const TESTIMONIALS = [
  { quote: "My hyperpigmentation faded in weeks. I have never trusted a brand like this.",
    name: "Amaka O.", where: "Lagos", avatar: "/home/avatars/a1.svg" },
  { quote: "Finally — skincare that understands melanin-rich skin AND ships to the UK fast.",
    name: "Tolu A.", where: "London", avatar: "/home/avatars/a2.svg" },
  { quote: "The whole family uses the baby oil. Gentle, rich, zero reactions.",
    name: "Zainab K.", where: "Abuja", avatar: "/home/avatars/a3.svg" },
  { quote: "Texture, scent, results. This is luxury without the luxury markup.",
    name: "Chidi N.", where: "Toronto", avatar: "/home/avatars/a4.svg" },
];

export const COMMUNITY = Array.from({ length: 6 }, (_, i) => ({
  image: `/home/community/post-${i + 1}.svg`,
  alt: "Toke community — real routines, real skin",
}));

export const EDUCATION = [
  { title: "The melanin-rich skin guide to vitamin C", href: "/page/blog", image: "/home/education.svg" },
  { title: "Hyperpigmentation: what actually works", href: "/page/blog", image: "/home/education.svg" },
  { title: "Building a 3-step routine that sticks", href: "/page/blog", image: "/home/education.svg" },
];

export const FEATURED_COLLECTION = {
  slug: "glow-naturally",
  title: "Glow Naturally",
  sub: "The curated edit for radiant, even-toned skin.",
  image: "/home/collection-banner.svg",
};
