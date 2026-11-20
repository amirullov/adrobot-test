const createForm = document.querySelector("#create-form");
const importForm = document.querySelector("#import-form");
const offerSelect = document.querySelector("#create-offer");
const offerSearch = document.querySelector("#create-offer-search");
const createStatus = document.querySelector("#create-status");
const campaignList = document.querySelector("#campaign-list");

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || "Request failed");
  return data;
}

async function loadOffers(query = "") {
  const items = await api(`/api/offers?q=${encodeURIComponent(query)}`);
  offerSelect.innerHTML = `<option value="">Select an offer</option>` + items.map(
    item => `<option value="${item.id}">${escapeHtml(item.name)} · #${item.id}</option>`
  ).join("");
}

async function loadCampaigns() {
  try {
    const items = await api("/api/campaigns");
    campaignList.innerHTML = items.length ? items.map(item => `
      <a class="campaign-item" href="/campaigns/${item.id}">
        <div><strong>${escapeHtml(item.name)}</strong><span>KT #${item.keitaro_campaign_id} · ${item.country_code}</span></div>
        <span>${item.dirty ? "Draft pending" : `${item.rows.length} offers`}</span>
      </a>`).join("") : `<p class="muted">No local campaigns yet.</p>`;
  } catch (error) {
    campaignList.innerHTML = `<p class="form-status error">${escapeHtml(error.message)}</p>`;
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

let searchTimer;
offerSearch.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadOffers(offerSearch.value).catch(showCreateError), 180);
});

function showCreateError(error) {
  createStatus.className = "form-status error";
  createStatus.textContent = error.message;
}

createForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = createForm.querySelector("button[type=submit]");
  button.disabled = true;
  createStatus.className = "form-status";
  createStatus.textContent = "Creating campaign and two streams…";
  const values = new FormData(createForm);
  try {
    const result = await api("/api/campaigns", {
      method: "POST",
      headers: {"Idempotency-Key": crypto.randomUUID()},
      body: JSON.stringify({
        name: values.get("name"),
        country_code: values.get("country_code"),
        offer_id: Number(values.get("offer_id")),
      }),
    });
    location.assign(`/campaigns/${result.id}`);
  } catch (error) {
    showCreateError(error);
    button.disabled = false;
  }
});

importForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = importForm.querySelector("button");
  button.disabled = true;
  const values = new FormData(importForm);
  try {
    const result = await api("/api/campaigns/import", {
      method: "POST",
      body: JSON.stringify({keitaro_campaign_id: Number(values.get("keitaro_campaign_id"))}),
    });
    location.assign(`/campaigns/${result.id}`);
  } catch (error) {
    alert(error.message);
    button.disabled = false;
  }
});

document.querySelector("#refresh-list").addEventListener("click", loadCampaigns);
loadOffers().catch(showCreateError);
loadCampaigns();
