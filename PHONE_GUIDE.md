# Opening Job Search from your phone

The website normally opens only on the Mac it runs on. With Tailscale, a free app, your phone can
open it too, from anywhere, over a private link between your own devices. Nobody else can reach
it: the page is not put on the internet.

What you need:

- Job Search running on your Mac, and the Mac awake (step 7).
- The Tailscale app on the Mac and on your phone, signed in to the same account.

## Step 1. Install Tailscale on the Mac

Install it from the Mac App Store (search for "Tailscale") or from tailscale.com/download. Open it
and sign in with your Google, Apple or Microsoft account. A Tailscale icon appears in the menu bar.

## Step 2. Install Tailscale on your phone

Install "Tailscale" from the App Store or Google Play, and sign in with the same account. Switch it
on. Both devices now appear in the app's list.

## Step 3. Find the Mac's Tailscale name

Open the Terminal app on the Mac and run:

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale status --self --json | grep -m1 DNSName
```

It prints a name like `"DNSName": "alex-mac.tail1234.ts.net."`. That name, without the quotes and the
last dot, is the Mac's address on your private network: here `alex-mac.tail1234.ts.net`.

To type `tailscale` instead of the long path in the steps below, run this once:

```bash
alias tailscale="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
```

## Step 4. Tell Job Search the name

Open the `.env` file in the project folder in a text editor and add one line, with your Mac's name:

```
JOBAGENT_WEB_HOSTS=alex-mac.tail1234.ts.net
```

Save the file. Then restart Job Search: on the website, Settings, **Stop Job Search**, then
double-click **Job Search** again. The page answers to that name only after this line is added; any
other name is still refused.

## Step 5. Share the page with your own devices

In the Terminal, run:

```bash
tailscale serve --bg 8765
```

The first time, it may print a link to switch on HTTPS for your Tailscale network: open it, switch
it on, and run the command again. It then prints the address, such as
`https://alex-mac.tail1234.ts.net/`. It keeps working after the Terminal is closed and after a
restart of the Mac.

Use `serve`, never `funnel`: `tailscale funnel` would put the page on the public internet.

## Step 6. Open it on your phone

With Tailscale switched on in the phone, open the address from step 5 in the phone's browser. The
same website appears, laid out for a phone. To keep it one tap away, add it to the home screen:
in Safari, Share, then **Add to Home Screen**; in Chrome, the menu, then **Add to Home screen**.

On the Mac, Settings, **Setup**, the line **From your phone** shows the address once step 4 is done.

## Step 7. Keep the Mac awake

The phone can reach the page only while the Mac is awake and Job Search is running. To keep a Mac
on its charger awake with the lid open: System Settings, **Battery** (or **Energy**), **Options**,
and switch on **Prevent automatic sleeping on power adapter when the display is off**. A Mac with
its lid closed sleeps unless a monitor is connected.

## Switching it off

```bash
tailscale serve reset
```

Then remove the `JOBAGENT_WEB_HOSTS` line from `.env` and restart Job Search.

## Is it safe?

- The page is reachable only from devices signed in to your own Tailscale account. Tailscale
  encrypts the link, and `serve` does not open it to the internet.
- Job Search still checks every request: it answers only to the names you listed, and everything
  beyond the page itself needs the key that the page carries.
- Anyone holding your unlocked phone can use the page, the same as anyone at your unlocked Mac.
  Sending an email still asks first.
