function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") : "";
}

document.getElementById("submitBtn").addEventListener("click", async () => {
  const email = document.getElementById("email").value;
  const errorBox = document.getElementById("errorBox");
  const successBox = document.getElementById("successBox");
  const btn = document.getElementById("submitBtn");
  errorBox.style.display = "none";
  successBox.style.display = "none";
  btn.disabled = true;

  try {
    const resp = await fetch("/api/auth/forgot-password", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ email }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      errorBox.textContent = (data.details && data.details[0] && data.details[0].message) || data.error || "Something went wrong.";
      errorBox.style.display = "block";
      return;
    }
    successBox.textContent = data.message;
    successBox.style.display = "block";
  } catch (err) {
    errorBox.textContent = "Couldn't reach the server.";
    errorBox.style.display = "block";
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("email").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("submitBtn").click();
});
