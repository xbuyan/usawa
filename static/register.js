function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") : "";
}

document.getElementById("registerBtn").addEventListener("click", async () => {
  const organization_name = document.getElementById("orgName").value;
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const errorBox = document.getElementById("errorBox");
  errorBox.style.display = "none";

  try {
    const resp = await fetch("/api/auth/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ email, password, organization_name }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      errorBox.textContent = data.error || "Registration failed.";
      errorBox.style.display = "block";
      return;
    }
    window.location.href = "/app";
  } catch (err) {
    errorBox.textContent = "Couldn't reach the server.";
    errorBox.style.display = "block";
  }
});

document.getElementById("password").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("registerBtn").click();
});
