function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute("content") : "";
}

document.getElementById("submitBtn").addEventListener("click", async () => {
  const token = document.getElementById("token").value;
  const new_password = document.getElementById("newPassword").value;
  const errorBox = document.getElementById("errorBox");
  const successBox = document.getElementById("successBox");
  errorBox.style.display = "none";
  successBox.style.display = "none";

  try {
    const resp = await fetch("/api/auth/reset-password", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({ token, new_password }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      errorBox.textContent = (data.details && data.details[0] && data.details[0].message) || data.error || "Something went wrong.";
      errorBox.style.display = "block";
      return;
    }
    successBox.textContent = data.message;
    successBox.style.display = "block";
    document.getElementById("submitBtn").style.display = "none";
    setTimeout(() => { window.location.href = "/login"; }, 1500);
  } catch (err) {
    errorBox.textContent = "Couldn't reach the server.";
    errorBox.style.display = "block";
  }
});

document.getElementById("newPassword").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("submitBtn").click();
});
