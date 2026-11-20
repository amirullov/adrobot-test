const root = document.querySelector("#editor");
const campaignId = Number(root.dataset.campaignId);
const rowsElement = document.querySelector("#offer-rows");
const errorBanner = document.querySelector("#error-banner");
const dirtyBanner = document.querySelector("#dirty-banner");
const offersDialog = document.querySelector("#offers-dialog");
const allOffers = document.querySelector("#all-offers");
const offerSearch = document.querySelector("#offer-search");
let campaign = null;
let offers = [];

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message || "Request failed");
    error.code = data.error?.code;
    throw error;
  }
  return data;
}

function showError(error) {
  errorBanner.textContent = error.message;
  errorBanner.classList.remove("hidden");
}

function clearError() { errorBanner.classList.add("hidden"); }

function toast(message) {
  const element = document.querySelector("#toast");
  element.textContent = message;
  element.classList.add("visible");
  setTimeout(() => element.classList.remove("visible"), 2600);
}

function render() {
  document.querySelector("#campaign-name").textContent = campaign.name;
  document.querySelector("#crumb-name").textContent = campaign.name;
  document.querySelector("#campaign-meta").textContent = `KT #${campaign.keitaro_campaign_id} · ${campaign.country_code} · offer stream #${campaign.offer_stream_id}`;
  document.querySelector("#view-kt").href = campaign.keitaro_url;
  document.querySelector("#google-stream").textContent = campaign.google_stream_id ? `Stream #${campaign.google_stream_id} is protected from edits.` : "No Google stream was identified; this editor still changes only the offer stream.";
  document.querySelector("#sync-state").textContent = campaign.syncing ? "Syncing…" : campaign.dirty ? `Draft v${campaign.draft_version}` : "Saved state";
  dirtyBanner.classList.toggle("hidden", !campaign.dirty);
  document.querySelector("#push-button").disabled = campaign.syncing;
  document.querySelector("#cancel-button").disabled = campaign.syncing;
  rowsElement.innerHTML = campaign.rows.length ? campaign.rows.map(row => `
    <tr class="offer-row ${row.state === "removed" ? "removed" : ""}">
      <td><strong>${escapeHtml(row.name)}</strong><small>Offer #${row.offer_id}</small></td>
      <td><span class="share">${row.share}%</span></td>
      <td><span class="placeholder">—</span></td>
      <td><span class="placeholder">—</span></td>
      <td class="actions-cell">${row.state === "removed"
        ? `<button data-action="bring-back" data-offer-id="${row.offer_id}">Bring Back</button>`
        : `<button class="danger-text" data-action="remove" data-offer-id="${row.offer_id}">Remove</button>`}</td>
    </tr>`).join("") : `<tr><td colspan="5"><p class="form-status error">No offers. Add at least one before Push.</p></td></tr>`;
  if (campaign.last_error) showError(new Error(campaign.last_error));
}

async function mutate(path, options = {}, successMessage = "Draft updated") {
  clearError();
  try {
    campaign = await api(path, options);
    render();
    toast(successMessage);
  } catch (error) {
    showError(error);
    if (error.code === "stale_draft") await loadCampaign();
  }
}

async function loadCampaign() {
  clearError();
  campaign = await api(`/api/campaigns/${campaignId}`);
  render();
}

rowsElement.addEventListener("click", event => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const offerId = Number(button.dataset.offerId);
  if (button.dataset.action === "remove") {
    mutate(`/api/campaigns/${campaignId}/draft/offers/${offerId}?version=${campaign.draft_version}`, {method: "DELETE"}, "Offer removed from local draft");
  } else {
    mutate(`/api/campaigns/${campaignId}/draft/offers/${offerId}/bring-back`, {method: "POST", body: JSON.stringify({version: campaign.draft_version})}, "Offer restored");
  }
});

document.querySelector("#fetch-button").addEventListener("click", event => {
  event.currentTarget.disabled = true;
  mutate(`/api/campaigns/${campaignId}/fetch`, {method: "POST"}, "Streams refreshed").finally(() => event.currentTarget.disabled = false);
});

document.querySelector("#cancel-button").addEventListener("click", () => {
  mutate(`/api/campaigns/${campaignId}/draft/cancel`, {method: "POST", body: JSON.stringify({version: campaign.draft_version})}, "Local changes cancelled");
});

document.querySelector("#push-button").addEventListener("click", event => {
  event.currentTarget.disabled = true;
  mutate(`/api/campaigns/${campaignId}/push`, {method: "POST", body: JSON.stringify({version: campaign.draft_version})}, "Saved to Keitaro").finally(() => event.currentTarget.disabled = false);
});

async function loadOffers(query = "") {
  offers = await api(`/api/offers?q=${encodeURIComponent(query)}`);
  const activeIds = new Set(campaign.rows.filter(row => row.state === "active").map(row => row.offer_id));
  allOffers.innerHTML = offers.length ? offers.map(offer => `
    <div class="offer-choice"><div><strong>${escapeHtml(offer.name)}</strong><span>Offer #${offer.id}</span></div>
    <button data-add-offer="${offer.id}" ${activeIds.has(offer.id) ? "disabled" : ""}>${activeIds.has(offer.id) ? "Added" : "Add"}</button></div>`
  ).join("") : `<p class="honesty-note">No matching active offers.</p>`;
}

document.querySelector("#show-offers-button").addEventListener("click", async () => {
  clearError();
  try { await loadOffers(); offersDialog.showModal(); } catch (error) { showError(error); }
});

let searchTimer;
offerSearch.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadOffers(offerSearch.value).catch(showError), 180);
});

allOffers.addEventListener("click", async event => {
  const button = event.target.closest("button[data-add-offer]");
  if (!button) return;
  button.disabled = true;
  try {
    campaign = await api(`/api/campaigns/${campaignId}/draft/offers`, {
      method: "POST",
      body: JSON.stringify({offer_id: Number(button.dataset.addOffer), version: campaign.draft_version}),
    });
    render();
    await loadOffers(offerSearch.value);
    toast("Offer added to local draft");
  } catch (error) { showError(error); button.disabled = false; }
});

loadCampaign().catch(showError);
