# SiteFinder (curated list) — Setup & Deploy

A simple static page that shows a list of SharePoint sites *you* choose.
Users can search, filter by category, **Open** a site, or **Request access**.
No sign-in, no Entra app, no Graph permissions — just edit a list and deploy.

~5 minutes.

---

## Step 1 — Edit your site list

Open `index.html` and edit the `SITES` array near the top:

```js
window.SITES = [
  {
    name: "HR & Benefits",
    url: "https://YOURTENANT.sharepoint.com/sites/HR",
    description: "Policies, PTO, benefits enrollment.",
    category: "Company"
  },
  // add as many as you like…
];
```

- `name` and `url` are required. `description` and `category` are optional.
- `category` becomes a filter chip at the top (sites with the same category group together). Leave it off to skip filtering.
- Tip: in SharePoint, the site URL is what's in the address bar, e.g. `https://contoso.sharepoint.com/sites/Finance`.

Save the file.

---

## Step 2 — Deploy to Netlify

1. Put `index.html` in a folder by itself.
2. Go to **app.netlify.com → Add new site → Deploy manually**.
3. Drag the folder onto the page. You get a URL like `https://your-name.netlify.app`.
4. (Optional) **Site settings → Change site name** to brand it.

That's the whole deploy. Updating the list later = edit `index.html`, drag the folder again (or connect a Git repo for auto-deploys).

---

## Step 3 — Put it on people's desktops

- **Manual:** right-click desktop → New → Shortcut → paste the Netlify URL.
- **At scale (Intune):** Apps → Windows → add a **Web link** pointed at the URL; it appears on the Start menu / desktop for a group.
- **Group Policy:** push a `.url` file to `%PUBLIC%\Desktop`:
  ```
  [InternetShortcut]
  URL=https://YOURAPP.netlify.app/
  ```
- **Or skip the desktop:** pin the URL as a Teams tab or add it to the SharePoint app bar.

---

## How "Request access" works

- **Default (no setup):** the button opens the site. If the user lacks permission, **SharePoint's own "request access" page appears automatically** and routes to the site owner. This is usually all you need.
- **Tracked approvals (optional):** create a Power Automate flow with a **"When an HTTP request is received"** trigger (payload `{ "siteName": "...", "siteUrl": "..." }`), add an Approval + "Add member" step, then paste the flow's URL into `window.REQUEST_WEBHOOK_URL` in `index.html` and redeploy.

---

## When to graduate to the auto-discovery version

This curated version is best when there's a known set of sites people need.
If you'd rather the app **automatically list every site each user can see**
(no manual list to maintain), that's the Microsoft Graph version — it needs a
quick Entra app registration. Ask and I'll hand that one back.
