const DATA_URL = "./data/clubs-idf.json";
const IDF_CENTER = [48.8566, 2.3522];
const IDF_BOUNDS = [
  [48.10, 1.45],
  [49.25, 3.55]
];

const DEPARTMENT_NAMES = {
  "75": "75 - Paris",
  "77": "77 - Seine-et-Marne",
  "78": "78 - Yvelines",
  "91": "91 - Essonne",
  "92": "92 - Hauts-de-Seine",
  "93": "93 - Seine-Saint-Denis",
  "94": "94 - Val-de-Marne",
  "95": "95 - Val-d'Oise"
};

const COLOR_BY_BUCKET = {
  national: "#E70000",
  prenat: "#f59e0b",
  regional: "#2563eb",
  departemental: "#6b7280",
  unknown: "#111827"
};

const map = L.map("map", {
  preferCanvas: true,
  scrollWheelZoom: true
}).setView(IDF_CENTER, 9);

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);

const markerLayer = L.layerGroup().addTo(map);
let allClubs = [];
let allCompetitions = [];
let currentMarkers = [];

const elements = {
  statusCard: document.getElementById("statusCard"),
  counter: document.getElementById("counter"),
  searchClub: document.getElementById("searchClub"),
  niveauFilter: document.getElementById("niveauFilter"),
  departementFilter: document.getElementById("departementFilter"),
  genreFilter: document.getElementById("genreFilter"),
  categorieFilter: document.getElementById("categorieFilter"),
  competitionFilter: document.getElementById("competitionFilter"),
  pouleFilter: document.getElementById("pouleFilter"),
  resetFilters: document.getElementById("resetFilters")
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalize(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) =>
    String(a).localeCompare(String(b), "fr", { numeric: true })
  );
}

function selectedValues(select) {
  return [...select.selectedOptions].map((option) => option.value);
}

function setOptions(select, values, labelFormatter = (value) => value) {
  const previous = new Set(selectedValues(select));
  select.innerHTML = "";

  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labelFormatter(value);
    option.selected = previous.has(value);
    select.appendChild(option);
  });
}

function bestEngagement(club) {
  const engagements = club.engagements || [];
  if (!engagements.length) return null;
  return [...engagements].sort((a, b) => (a.level_rank ?? 999) - (b.level_rank ?? 999))[0];
}

function colorBucket(engagement) {
  const niveau = normalize(engagement?.niveau || engagement?.competition_code || engagement?.competition_nom);

  if (/\b(nm|nf)[123]\b/.test(niveau) || niveau.includes("nationale")) return "national";
  if (niveau.includes("pnm") || niveau.includes("pnf") || niveau.includes("pre nationale") || niveau.includes("pré nationale")) return "prenat";
  if (niveau.includes("rm1") || niveau.includes("rf1") || niveau.includes("division 1")) return "prenat";
  if (niveau.includes("rm") || niveau.includes("rf") || niveau.includes("regionale") || niveau.includes("régionale")) return "regional";
  if (niveau.includes("dm") || niveau.includes("df") || niveau.includes("departement")) return "departemental";

  return "unknown";
}

function markerIcon(bucket) {
  const color = COLOR_BY_BUCKET[bucket] || COLOR_BY_BUCKET.unknown;
  return L.divIcon({
    className: "club-marker",
    html: `<div class="marker-pin" style="background:${color}"></div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -10]
  });
}

function buildPopup(club, matchingEngagements) {
  const best = bestEngagement({ engagements: matchingEngagements }) || bestEngagement(club);
  const teams = matchingEngagements
    .map((engagement) => {
      const parts = [
        engagement.niveau || engagement.competition_code,
        engagement.competition_nom,
        engagement.poule,
        engagement.equipe_nom
      ].filter(Boolean);
      return `<li>${escapeHtml(parts.join(" · "))}</li>`;
    })
    .join("");

  const sourceLink = club.url
    ? `<p class="popup-meta"><a href="${escapeHtml(club.url)}" target="_blank" rel="noreferrer">Voir la fiche FFBB</a></p>`
    : "";

  return `
    <div class="popup-title">${escapeHtml(club.nom)}</div>
    <p class="popup-meta">${escapeHtml(club.adresse || "Adresse non renseignée")}</p>
    <p class="popup-meta">${escapeHtml(club.code_postal || "")} ${escapeHtml(club.ville || "")}</p>
    <p class="popup-meta"><strong>Niveau principal :</strong> ${escapeHtml(best?.niveau || "Non classé")}</p>
    <ul class="popup-teams">${teams || "<li>Aucun engagement filtré</li>"}</ul>
    ${sourceLink}
  `;
}

function engagementMatchesFilters(engagement, filters) {
  if (filters.niveaux.length && !filters.niveaux.includes(engagement.niveau)) return false;
  if (filters.genres.length && !filters.genres.includes(engagement.genre)) return false;
  if (filters.categories.length && !filters.categories.includes(engagement.categorie)) return false;
  if (filters.competitions.length && !filters.competitions.includes(engagement.competition_slug)) return false;
  if (filters.poules.length && !filters.poules.includes(engagement.poule)) return false;
  return true;
}

function clubMatchesFilters(club, filters) {
  if (filters.departements.length && !filters.departements.includes(club.departement)) return false;

  if (filters.search) {
    const haystack = normalize([club.nom, club.ville, club.adresse].filter(Boolean).join(" "));
    if (!haystack.includes(filters.search)) return false;
  }

  const matchingEngagements = (club.engagements || []).filter((engagement) => engagementMatchesFilters(engagement, filters));
  return matchingEngagements.length ? matchingEngagements : false;
}

function getFilters() {
  return {
    search: normalize(elements.searchClub.value),
    niveaux: selectedValues(elements.niveauFilter),
    departements: selectedValues(elements.departementFilter),
    genres: selectedValues(elements.genreFilter),
    categories: selectedValues(elements.categorieFilter),
    competitions: selectedValues(elements.competitionFilter),
    poules: selectedValues(elements.pouleFilter)
  };
}

function filteredEngagementsForDynamicLists(baseFilters) {
  return allClubs.flatMap((club) => {
    if (baseFilters.departements.length && !baseFilters.departements.includes(club.departement)) return [];
    if (baseFilters.search) {
      const haystack = normalize([club.nom, club.ville, club.adresse].filter(Boolean).join(" "));
      if (!haystack.includes(baseFilters.search)) return [];
    }
    return club.engagements || [];
  });
}

function refreshDependentOptions() {
  const filters = getFilters();
  const engagements = filteredEngagementsForDynamicLists(filters);

  setOptions(elements.niveauFilter, uniqueSorted(engagements.map((e) => e.niveau)));
  setOptions(elements.genreFilter, uniqueSorted(engagements.map((e) => e.genre)));
  setOptions(elements.categorieFilter, uniqueSorted(engagements.map((e) => e.categorie)));
  setOptions(
    elements.competitionFilter,
    uniqueSorted(engagements.map((e) => e.competition_slug)),
    (slug) => allCompetitions.find((competition) => competition.slug === slug)?.nom || slug
  );
  setOptions(elements.pouleFilter, uniqueSorted(engagements.map((e) => e.poule)));
}

function renderMap() {
  const filters = getFilters();
  markerLayer.clearLayers();
  currentMarkers = [];

  const visible = [];

  allClubs.forEach((club) => {
    if (club.lat == null || club.lon == null) return;

    const matchingEngagements = clubMatchesFilters(club, filters);
    if (!matchingEngagements) return;

    const best = bestEngagement({ engagements: matchingEngagements }) || bestEngagement(club);
    const bucket = colorBucket(best);

    const marker = L.marker([club.lat, club.lon], { icon: markerIcon(bucket) })
      .bindPopup(buildPopup(club, matchingEngagements));

    markerLayer.addLayer(marker);
    currentMarkers.push(marker);
    visible.push(club);
  });

  const count = visible.length;
  elements.counter.textContent = `${count} club${count > 1 ? "s" : ""} affiché${count > 1 ? "s" : ""}`;

  if (currentMarkers.length) {
    const group = L.featureGroup(currentMarkers);
    map.fitBounds(group.getBounds().pad(0.16), { maxZoom: 12 });
  }
}

function updateStatus(data) {
  const generatedAt = data.metadata?.generated_at;
  const clubsCount = allClubs.length;
  const geocodedCount = allClubs.filter((club) => club.lat != null && club.lon != null).length;

  if (!clubsCount) {
    elements.statusCard.classList.add("warning");
    elements.statusCard.innerHTML = `
      <strong>Données non générées</strong>
      <span>Lance le workflow GitHub Actions ou <code>python scripts/build_data.py</code>.</span>
    `;
    return;
  }

  elements.statusCard.classList.remove("warning", "error");
  elements.statusCard.innerHTML = `
    <strong>${clubsCount} club${clubsCount > 1 ? "s" : ""} chargé${clubsCount > 1 ? "s" : ""}</strong>
    <span>${geocodedCount} avec coordonnées GPS · MAJ ${generatedAt || "non renseignée"}</span>
  `;
}

function initializeFilters() {
  const engagements = allClubs.flatMap((club) => club.engagements || []);
  setOptions(elements.departementFilter, uniqueSorted(allClubs.map((club) => club.departement)), (dep) => DEPARTMENT_NAMES[dep] || dep);
  setOptions(elements.niveauFilter, uniqueSorted(engagements.map((e) => e.niveau)));
  setOptions(elements.genreFilter, uniqueSorted(engagements.map((e) => e.genre)));
  setOptions(elements.categorieFilter, uniqueSorted(engagements.map((e) => e.categorie)));
  setOptions(
    elements.competitionFilter,
    uniqueSorted(engagements.map((e) => e.competition_slug)),
    (slug) => allCompetitions.find((competition) => competition.slug === slug)?.nom || slug
  );
  setOptions(elements.pouleFilter, uniqueSorted(engagements.map((e) => e.poule)));
}

function attachEvents() {
  [
    elements.searchClub,
    elements.niveauFilter,
    elements.departementFilter,
    elements.genreFilter,
    elements.categorieFilter,
    elements.competitionFilter,
    elements.pouleFilter
  ].forEach((element) => {
    element.addEventListener("input", () => {
      refreshDependentOptions();
      renderMap();
    });
    element.addEventListener("change", () => {
      refreshDependentOptions();
      renderMap();
    });
  });

  elements.resetFilters.addEventListener("click", () => {
    elements.searchClub.value = "";
    [
      elements.niveauFilter,
      elements.departementFilter,
      elements.genreFilter,
      elements.categorieFilter,
      elements.competitionFilter,
      elements.pouleFilter
    ].forEach((select) => {
      [...select.options].forEach((option) => {
        option.selected = false;
      });
    });
    initializeFilters();
    renderMap();
    map.fitBounds(IDF_BOUNDS);
  });
}

async function main() {
  try {
    const response = await fetch(DATA_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    allClubs = data.clubs || [];
    allCompetitions = data.competitions || [];

    initializeFilters();
    attachEvents();
    updateStatus(data);
    renderMap();

    if (!allClubs.length) map.fitBounds(IDF_BOUNDS);
  } catch (error) {
    elements.statusCard.classList.add("error");
    elements.statusCard.innerHTML = `
      <strong>Impossible de charger les données</strong>
      <span>${escapeHtml(error.message)}</span>
    `;
    elements.counter.textContent = "0 club affiché";
    map.fitBounds(IDF_BOUNDS);
  }
}

main();
