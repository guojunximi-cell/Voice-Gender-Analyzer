/**
 * disclosure-modal.js — One-time ethical / scope disclosure gate.
 *
 * On first visit, blocks the UI with a modal stating that the tool measures
 * (not prescribes), is not a substitute for a voice teacher, and may worsen
 * dysphoria when consulted in a bad-state moment. After the user clicks
 * "I understand", a localStorage flag is set so the modal stays dismissed.
 *
 * The same modal is re-openable from a header "About" button via
 * `showDisclosure()`, in which case the X close is shown and acknowledge
 * is hidden — there's nothing left to acknowledge once it's already done.
 *
 * Bumping the LS_KEY suffix (currently `_v1`) on policy revisions forces
 * everyone to see the modal again — equivalent to a re-consent.
 */

const LS_KEY = "vga.disclosureAcked.v1";

function _isAcked() {
	try {
		return localStorage.getItem(LS_KEY) === "1";
	} catch {
		// localStorage unavailable (private mode, blocked) → treat as not
		// acked but don't block forever; second visit will hit the same
		// path. Worst case: user sees disclosure every time.
		return false;
	}
}

function _setAcked() {
	try {
		localStorage.setItem(LS_KEY, "1");
	} catch {
		/* ignore — see _isAcked */
	}
}

function _show(mode) {
	const modal = document.getElementById("disclosure-modal");
	if (!modal) return;
	const closeBtn = document.getElementById("disclosure-close");
	const ackBtn = document.getElementById("disclosure-acknowledge");
	if (mode === "first-launch") {
		if (closeBtn) closeBtn.hidden = true;
		if (ackBtn) ackBtn.hidden = false;
	} else {
		// review mode (footer / header link): X to close, ack already done
		if (closeBtn) closeBtn.hidden = false;
		if (ackBtn) ackBtn.hidden = true;
	}
	modal.classList.add("show");
	document.body.style.overflow = "hidden";
}

function _hide() {
	const modal = document.getElementById("disclosure-modal");
	if (!modal) return;
	modal.classList.remove("show");
	document.body.style.overflow = "";
}

function _bindOnce() {
	const modal = document.getElementById("disclosure-modal");
	if (!modal || modal.dataset.bound) return;
	modal.dataset.bound = "1";

	const closeBtn = document.getElementById("disclosure-close");
	closeBtn?.addEventListener("click", _hide);

	const ackBtn = document.getElementById("disclosure-acknowledge");
	ackBtn?.addEventListener("click", () => {
		_setAcked();
		_hide();
	});

	const backdrop = document.getElementById("disclosure-backdrop");
	// Backdrop click closes ONLY in review mode — first-launch users must
	// commit to the acknowledge button so a misclick can't bypass consent.
	backdrop?.addEventListener("click", () => {
		const ackHidden = ackBtn?.hidden;
		if (ackHidden) _hide();
	});

	document.addEventListener("keydown", (e) => {
		if (e.key !== "Escape") return;
		if (!modal.classList.contains("show")) return;
		// Same rule as backdrop: only review mode lets Escape close.
		if (ackBtn?.hidden) _hide();
	});
}

/** Call once on boot. Shows the modal if the user hasn't acked yet. */
export function mountDisclosureModal() {
	_bindOnce();
	if (!_isAcked()) _show("first-launch");
}

/** Re-open the disclosure later (from an About link / header button). */
export function showDisclosure() {
	_bindOnce();
	_show("review");
}
