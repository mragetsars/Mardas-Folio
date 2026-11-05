# سیستم طراحی و معماری رابط Mardas Folio 2.1

تاریخ بازبینی: ۲۰۲۶-۱۱-۰۴ تا ۲۰۲۶-۱۱-۰۵. این سند قرارداد مهندسی رابط است: اندازه‌ها، رفتار چیدمان، قواعد محتوا و معیارهای پذیرش باید هم در کد و هم در آزمون قابل سنجش باشند. مبنا، هفت تصویر ارائه‌شده و ساختار واقعی `apps/desktop/frontend` است. نام محصولات مرجع جهت کیفیت و سادگی را مشخص می‌کند؛ این سند ادعای پیروی رسمی از سیستم طراحی آن محصولات ندارد.

در تصویر ۷۲۸، هر چهار پنل بازند و تغییر عرض ادیتور، ابزارهای ثابت را به چند سطر تبدیل کرده است. در همان تصویر شناسه‌های کد داخل جدولِ پیش‌نمایش شکسته‌اند؛ خود جدول باید اسکرول افقی مستقل داشته باشد. تصویر ۷۲۳ برتری بیش‌ازحد کارت نارنجی و تکرار مسیرهای کامل را نشان می‌دهد. در تصویر ۷۲۴ نیز انتهای dock خروجی با لبهٔ ستون پیش‌نمایش هم‌خط نیست. این مشکلات از قراردادهای متفاوت اجزای پوسته می‌آیند؛ تغییر رنگ به‌تنهایی آن‌ها را حل نمی‌کند.

## ۱. توکن‌های طراحی و شبکه

### نقش سطوح و رنگ‌ها

تیره‌بودن به معنی پرکردن همهٔ سطوح با یک خاکستری نیست. کاغذ و فضای اصلی سیاه‌اند؛ کنترل‌ها با اختلاف روشنایی بسیار کم از آن جدا می‌شوند. نارنجی نشانهٔ کنش، انتخاب و فوکوس است؛ برای تزئین همهٔ کادرها استفاده نمی‌شود.

| توکن معنایی | Hex / HSL | کاربرد |
| --- | --- | --- |
| `--surface-canvas` | `#000000` / `hsl(0 0% 0%)` | بوم سند، زمینهٔ اصلی برنامه |
| `--surface-chrome` | `#09090B` / `hsl(240 10% 3.9%)` | نوار سراسری، پنل‌های ناوبری |
| `--surface-control` | `#101012` / `hsl(240 5.9% 6.7%)` | کادر ورودی، کارت آرام |
| `--surface-elevated` | `#18181B` / `hsl(240 5.9% 10%)` | منو، popup، دیالوگ و hover فرمان خنثی |
| `--text-primary` | `#F4F4F5` / `hsl(240 4.8% 95.9%)` | متن و عنوان اصلی |
| `--text-secondary` | `#D4D4D8` / `hsl(240 4.9% 83.9%)` | متن راهنما و برچسب ثانویه |
| `--text-muted` | `#A1A1AA` / `hsl(240 5% 64.9%)` | زمان، مسیر کوتاه، وضعیت غیرفعال |
| `--accent` | `#F59E0B` / `hsl(37.7 92.1% 50.2%)` | کنش اصلی، نشان انتخاب، فوکوس |
| `--accent-hover` | `#FBBF24` / `hsl(43.3 96.4% 56.3%)` | hover کنش اصلی |
| `--on-accent` | `#1C1202` | نوشته و آیکون روی زمینهٔ نارنجی |
| `--border-subtle` | `rgba(255,255,255,.07)` | خط مشترک پنل، ورودی، جدول |
| `--border-interactive` | `rgba(255,255,255,.18)` | hover ورودی و مرز قابل‌تعامل |
| `--accent-wash` | `rgba(245,158,11,.12)` | انتخاب آرام یک تب یا ردیف |
| `--selection` | `rgba(245,158,11,.28)` | انتخاب متنِ دارای فوکوس |
| `--selection-inactive` | `rgba(245,158,11,.16)` | انتخاب متن پس از خروج فوکوس |

رنگ متنِ پوستهٔ روشن باید نقش مستقل داشته باشد: نارنجی روشن روی سفید برای نوشتهٔ کوچک کافی نیست. در حالت روشن می‌توان از مرکب قهوه‌ای تیره برای متن تأکیدی و همان amber برای سطح دکمه استفاده کرد. سند و پیش‌نمایش نباید با تغییر پوسته، قواعد چینش یا اندازهٔ کنترل متفاوت پیدا کنند.

```css
html[data-theme="dark"] {
  --surface-canvas: #000;
  --surface-chrome: #09090b;
  --surface-control: #101012;
  --surface-elevated: #18181b;
  --ui-bg: var(--surface-canvas);
  --ui-page: var(--surface-canvas);
  --ui-panel-soft: var(--surface-chrome);
  --ui-panel: var(--surface-control);
  --ui-panel-muted: var(--surface-elevated);
  --ui-border: rgb(255 255 255 / .07);
  --ui-border-strong: rgb(255 255 255 / .18);
  --ui-accent: #f59e0b;
  --ui-accent-fill: #f59e0b;
  --ui-accent-soft: rgb(245 158 11 / .12);
  --ui-on-accent: #1c1202;
  --cm-selection: rgb(245 158 11 / .28);
  --cm-selection-inactive: rgb(245 158 11 / .16);
}
```

### شبکه، شعاع و تراکم

| نقش | اندازهٔ دقیق | قاعده |
| --- | --- | --- |
| واحد پایه | `4px` | جزئیات کنترل و فاصلهٔ آیکون/متن |
| ضرب‌آهنگ اصلی | `8px` | فاصلهٔ اجزا و دسته‌بندی |
| مقیاس فاصله | `4, 8, 12, 16, 20, 24, 32, 40, 48px` | اندازهٔ دلخواه جدید بدون نیاز مشخص اضافه نشود |
| شعاع کوچک | `4px` | badge کد، ردیف فشرده |
| شعاع کنترل | `6px` | دکمه، segment و تب |
| شعاع متوسط | `8px` | ورودی و منوی کوچک |
| شعاع کارت | `12px` | کارت Home، خروجی، popup |
| شعاع دیالوگ | `16px` | دیالوگ مستقل |
| ارتفاع کنترل فشرده | `28px` | ابزار نوشتن، کنترل پنل |
| ارتفاع کنترل معمول | `32px` | ورودی متادیتا، دکمهٔ فرم |
| ارتفاع کنش مهم | `36px` | ذخیره و ایجاد PDF |
| آیکون پوسته | `16px`، stroke برابر `1.7` | آیکون محتوا یا برند استثنای معنایی دارد |
| نوار سراسری | `48px` | یک ردیف، ارتفاع ثابت |
| ردیف کنترل پنل | `40px` | یک ردیف هم‌خط برای همهٔ ستون‌ها |
| نوار وضعیت | `24–28px` | بر اساس توکن موجود و مقیاس رابط؛ ثابت در یک نشست |
| gutter صفحهٔ Home | `32px` | در عرض کوچک `20px` |
| gutter صفحهٔ Export | `24px` | در عرض کوچک `12px` |
| فاصلهٔ ستون Home/Export | `24px` | لبهٔ dock از همین container محاسبه می‌شود |

Border فقط در مرزهایی استفاده شود که اطلاعاتی را تفکیک می‌کنند: جداکنندهٔ پنل، کادر ورودی، جدول و popup. یک کارت داخل کارت نباید سه مرز هم‌پوشان بسازد. سطح و فاصله ابتدا سلسله‌مراتب را ایجاد می‌کنند؛ سایه فقط برای محتوای شناور است، نه همهٔ پنل‌های ثابت.

### تایپوگرافی و نقش فونت

| نقش | خانواده و fallback | اندازه و ارتفاع سطر |
| --- | --- | --- |
| UI لاتین و فارسی | `Inter`, `Segoe UI Variable`, `Segoe UI`, `Vazirmatn`, `Noto Sans Arabic`, `system-ui` | متن معمول `13px / 20px`؛ نوشتهٔ فرعی `12px / 18px` |
| متن سند | `Vazirmatn`, `Segoe UI`, `Noto Sans Arabic`, `sans-serif`؛ قابل‌تغییر با ترجیح کاربر | پایه `18px`؛ ضریب سطر از تنظیم تراکم `1.5 / 1.65 / 1.85` |
| Markdown سورس و کد | `ui-monospace`, `Cascadia Mono`, `SFMono-Regular`, `JetBrains Mono`, `Menlo`, `Consolas`, `Vazirmatn`, `Noto Sans Arabic`, `monospace` | پایه `14px / 1.65`؛ tab برابر چهار فاصله |
| نام سند / عنوان پنل | UI | `13px`، وزن `600` |
| مسیر و زمان | UI یا monospace در ابزار کامل مسیر | `11–12px`؛ هرگز متن اصلی برای تشخیص فایل نیست |

فونت فارسی باید حروف ترکیبی، نیم‌فاصله و اعراب را بدون بریدگی نشان دهد. برای متن فارسی `letter-spacing` اعمال نشود. اعداد رابط مانند zoom، شمارندهٔ نتیجه و شمارهٔ سطر `tabular-nums` دارند. مقیاس سند با مقیاس chrome یکی نیست: بزرگ‌کردن متن برای مطالعه نباید نوار ابزار را چندسطر کند.

## ۲. معماری پوسته و آزمون چهار پنل

### قرارداد دو ردیف

ردیف نخست، پوستهٔ مشترک Home، Export و Workspace است. در Workspace، تب‌های فایل داخل همین نوار سراسری قرار می‌گیرند و از عرض مشترک ادیتور و پیش‌نمایش استفاده می‌کنند؛ در بازشدن Inspector به اندازهٔ ستون ادیتور محدود نمی‌شوند. مسیر کامل و عنوان سند، ردیف سوم ایجاد نمی‌کنند.

ردیف دوم، کنترل‌های محلی چهار ستون است. همه دقیقاً `40px` ارتفاع دارند و محتوای هر ستون از خط `y = 88px` آغاز می‌شود. نوار عنوان بومی Windows بیرون از این محاسبه است.

```text
                 WIDTH: FULL APPLICATION / LOCAL LAYOUT DIRECTION
+-------------------------------------------------------------------------------+
| Brand | Go to file | document tabs across available width | Save | PDF | tools | 48
+------------------+--------------------------+------------------+---------------+
| Files | Outline  | Write Source Read …      | Document view …  | Inspector tabs| 40
+------------------+--------------------------+------------------+---------------+ y=88
|                  |                          |                  |               |
| Files / Outline  | Markdown editing canvas  | Same document    | Property grid |
|                  |                          | rendering        |               |
| independent      | Find is contextual,      | independent      | independently |
| vertical scroll  | inside this pane only    | vertical scroll  | scrolling body|
|                  |                          |                  |---------------|
| Open project     |                          |                  | Apply metadata|
+------------------+--------------------------+------------------+---------------+
| document metrics                                      line/column / status    |
+-------------------------------------------------------------------------------+
```

جهت فیزیکی این نمودار برای توضیح است. در رابط فارسی، ناوبری و Inspector می‌توانند با `inline-start/end` آینه شوند؛ هندسهٔ سند از زبان رابط تبعیت اجباری نمی‌کند. فایل انگلیسی در UI فارسی همچنان LTR است و برعکس.

### ساختار Grid/Flex

ساختار واقعی از `.topbar`، `.authoring-grid`، `.file-navigator`، `.editor-pane`، `.preview-pane` و `.author-sidebar` استفاده می‌کند. این اسکلت نقش‌ها و الزامات اندازه‌گذاری را نشان می‌دهد؛ جزئیات selectorهای حالت و breakpoint در `shell-system.css` نگه‌داری می‌شود.

```css
.shell {
  display: grid;
  grid-template-rows: 48px minmax(0, 1fr) var(--status-height, 28px);
  block-size: 100dvh;
  min-inline-size: 0;
  overflow: hidden;
}
.topbar {
  display: flex;
  align-items: center;
  block-size: 48px;
  min-inline-size: 0;
  gap: 8px;
  flex-wrap: nowrap;
}
.topbar .document-tabs {
  display: flex;
  flex: 1 1 0;
  min-inline-size: 0;
  overflow-x: auto;
  white-space: nowrap;
}
.authoring-grid {
  display: grid;
  min-inline-size: 0;
  min-block-size: 0;
  grid-template-columns:
    var(--files-track, 248px) var(--files-divider, 1px)
    minmax(0, 1fr)
    var(--preview-divider, 1px) var(--preview-track, 460px)
    var(--sidebar-divider, 1px) var(--sidebar-track, 296px);
}
.file-navigator,
.editor-pane,
.preview-pane,
.author-sidebar {
  min-inline-size: 0;
  min-block-size: 0;
  overflow: hidden;
  display: grid;
  grid-template-rows: 40px minmax(0, 1fr);
}
.document-toolbar,
.content-view-header,
.navigator-tabs,
.sidebar-tabs {
  min-inline-size: 0;
  block-size: 40px;
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  white-space: nowrap;
  border-block-end: 1px solid var(--ui-border);
}
```

نوار Find در ادیتور، ردیف شرطی و مرتبط با جست‌وجو است؛ در ارتفاع ثابت دو ردیف chrome شمارش نمی‌شود. بازشدن Find فقط فضای متن همان پنل را کاهش می‌دهد. نباید عنوان Preview یا Inspector را جابه‌جا کند. نتیجهٔ عملیات، toast و پیام «ذخیره شد» نیز ارتفاع پوسته را تغییر نمی‌دهند.

کنترل‌های به‌روزرسانی خودکار و Refresh در Read به همان ردیف ۴۰ پیکسلی منتقل شده‌اند؛ حذف ردیف اضافی، قابلیت را پنهان نمی‌کند. سند در `main` و ریشهٔ صفحه، ناحیهٔ اسکرول سراسری ندارد؛ فقط نواحی محتوایی اسکرول می‌کنند، تا برگشت از Read نتواند topbar را از صفحه بیرون ببرد.

در عرض دسکتاپ، `fitWorkspaceWidths()` از عرض موجود ابتدا ۳۲۰ پیکسل برای ادیتور و یک پیکسل برای هر جداکننده کنار می‌گذارد. اگر اندازه‌های درخواستی پنل‌ها بیشتر بود، فضای اضافه نسبت به حداقل هر پنل به نسبت کاهش می‌یابد. اندازه‌های ترجیحی ذخیره‌شده بازنویسی نمی‌شوند و در پنجرهٔ بزرگ‌تر برمی‌گردند. مقدار `aria-valuenow` جداکننده‌ها، عرض واقعیِ قابل مشاهده را گزارش می‌کند. نزدیک آستانهٔ drawer، حداقل پنل‌ها بر فضای ادیتور اولویت دارند؛ زیر ۱۱۰۰ پیکسل پنل‌های کناری overlay می‌شوند و زیر ۷۶۰ پیکسل Preview پایین ادیتور قرار می‌گیرد.

### رفتار ابزارها در عرض کم

ترتیب اولویت از «فعالیت» تا «تنظیم محیط» است:

1. Write / Source / Read همیشه در ردیف محلی باقی می‌مانند؛ این‌ها فعالیت‌های متفاوت‌اند.
2. فرمان‌های محتوایی مانند Bold، Link و Insert به‌صورت گروه کامل از نوار به منوی overflow همان ابزار منتقل می‌شوند.
3. اندازه/عرض/ظاهر متن گروه نمایش‌اند؛ در نبود جا، گروه به overflow نمایش می‌رود.
4. Side preview، Focus و Inspector گروه چیدمان‌اند؛ یک دکمهٔ `…` دسترسی به ابزارهای خارج‌شده را حفظ می‌کند.

هیچ گروهی `flex-wrap: wrap` ندارد. از صفرکردن عرض، بریدن نام، یا پنهان‌کردن بدون مسیر دسترسی استفاده نشود. عناصر واقعی DOM جابه‌جا شوند تا `id`، handler، `aria-pressed`، disabled و فوکوس یکتا بمانند؛ ساخت دکمهٔ دوم برای همان فرمان، منبع وضعیت متناقض می‌شود. overflow باید با Tab و Enter باز شود، با Escape بسته شود و فوکوس را به دکمهٔ بازکننده برگرداند.

مبنای تصمیم، عرض قابل‌استفادهٔ خود toolbar است، نه فقط `window.innerWidth`. `ResizeObserver` باید تغییر عرض ناشی از بازشدن پنل، تغییر اندازهٔ آن یا ترجمهٔ فارسی را تشخیص دهد. انتقال گروه‌ها در `requestAnimationFrame` انجام شود؛ متن سند، selection و Undo نباید با آن بازسازی شوند. بازگشت گروه‌ها با یک حاشیهٔ اندازهٔ چندپیکسلی انجام شود تا سر مرز، رفت‌وبرگشت سریع یا حلقهٔ ResizeObserver رخ ندهد.

| پیکربندی | قرارداد |
| --- | --- |
| فقط ادیتور | یک canvas، دو ردیف chrome، تب‌ها در عرض سراسری |
| ادیتور + پیش‌نمایش | headerها هم‌خط؛ ابزارهای کم‌اولویت به overflow می‌روند |
| ادیتور + یک sidebar | عرض sidebar از canvas کم می‌شود؛ ارتفاع header ثابت می‌ماند |
| چهار پنل در ۱۹۲۰×۱۰۸۰ | همهٔ headerها `40px`، تب‌ها بیرون ادیتور، هیچ toolbar چندسطر نمی‌شود |
| عرض‌های کوچک | sidebar به overlay تبدیل می‌شود؛ در حدی که دو canvas قابل استفاده نیستند، Preview در چیدمان کوچک به سطح مستقل/چیدمان زیرین می‌رود؛ اسکرول کل صفحه ایجاد نشود |
| Focus | chrome و پنل‌های پیرامونی طبق رفتار Focus پنهان می‌شوند؛ راه خروج روشن با Escape باقی می‌ماند |

«بدون جابه‌جایی چیدمان» در این قرارداد یعنی ارتفاع ثابت chrome، keylineهای ثابت و نگه‌داشتن caret/scroll هنگام تنظیم پنل. بازشدن آگاهانهٔ یک ستون طبیعتاً عرض canvas و شکست سطرها را عوض می‌کند؛ جلوگیری از reflow متن، هدف این طراحی نیست.

## ۳. برنامهٔ بازآرایی صفحه‌ها و اجزا

### Home

- نوار برند، وضعیت موتور و ابزارهای عمومی همان `.topbar` مشترک باشد.
- محتوای اصلی Home یک container با `max-inline-size: 1200px` و gutter مشترک `32px` داشته باشد. دو ستون آغاز کار و Recent از grid مشترک، gap برابر `24px` و baseline عنوان برابر استفاده کنند. عرض مستقل Export برابر `1280px` است؛ اجزای هر صفحه باید container همان صفحه را رعایت کنند.
- `#workflow-new` زمینهٔ خنثی مانند سایر ردیف‌ها داشته باشد. اولویت با متن، آیکون amber و wash ده‌درصدی مشخص شود؛ تمام سطح ردیف نارنجی نشود.
- Recent: نام فایل در سطر اول، پروژه یا یک/دو پوشهٔ پایانی در سطر دوم. مسیر کامل فقط در tooltip و قابلیت مشاهده/کپی مسیر در ابزار مربوطه باشد. مسیرِ ذخیره‌شده، شناسهٔ سند و دادهٔ IPC تغییر نمی‌کنند.
- کارت‌های template یک شعاع `8px`، padding برابر `16px` و آیکون `32px` دارند؛ ارتفاع از محتوای واقعی می‌آید و عنوان‌ها در عرض کم از کارت بیرون نمی‌زنند.

### Quick PDF Export

`#export-view` صاحب یک پهنای مشترک است. عنوان، `.export-layout` و `.export-dock` فرزندان همان container هستند. dock نباید عرض مستقل، offset متفاوت یا `100vw` داشته باشد.

```css
#export-view {
  --studio-max: 1280px;
  inline-size: 100%;
  max-inline-size: var(--studio-max);
  margin-inline: auto;
  min-inline-size: 0;
}
#export-view .export-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 440px);
  gap: 24px;
}
#export-view .export-dock {
  inline-size: 100%;
  max-inline-size: none;
  margin-inline: 0;
  box-sizing: border-box;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: end;
}
@media (max-width: 1000px) {
  #export-view .export-layout { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 640px) {
  #export-view .export-dock { grid-template-columns: minmax(0, 1fr); }
}
```

هندسهٔ sticky dock از parent محاسبه شود. محتوا باید تا آخرین گزینه اسکرول شود و فضای رزروشدهٔ dock مانع پوشانده‌شدن کنترل نهایی شود. Output file همچنان یک مسیر خروجی واقعی است؛ کوتاه‌نمایی نمایشی نباید مسیر ارسالی به موتور را عوض کند. دکمه‌های Check و Create PDF هم‌ارتفاع‌اند؛ فقط Create PDF زمینهٔ کامل amber می‌گیرد. پیام خطا نزدیک همان ورودی و گزارش رندر در پنل وضعیت است.

### ناوبری و Inspector

Files / Outline و تب‌های Inspector یک خانوادهٔ segment هستند: ارتفاع ردیف `40px`، track برابر `32px` با padding و gap برابر `2px`، کنترل `28px` و شعاع `4px` داخل track با شعاع `6px`. انتخاب با amber wash و متن amber مشخص می‌شود. تفاوت تعداد تب‌ها به معنی سیستم بصری متفاوت نیست. آیکونِ تنها باید label دسترس‌پذیر و tooltip داشته باشد؛ حالت فعال صرفاً با رنگ مشخص نشود و `aria-selected` همگام بماند.

عنوان‌های «Document navigation» و «Inspector» نباید یک header مستقل دیگر بالای این segment بسازند. نام پنل از accessible label و عنوان محتوای جاری قابل فهم است. ساخت سند و بازکردن فایل با ابزار سراسری قابل‌دسترسی‌اند؛ تکرار Ctrl+P در footer حذف می‌شود. footer ناوبری فقط کار پروژه را نگه می‌دارد.

در Outline، عمق در ستون مستقل و با `padding-inline-start: depth * 12px` اعمال شود. ستون chevron برابر `20px` و gap آن `2px` است و حتی برای برگ‌ها رزرو می‌ماند تا متن نسبت به سطر والد نپرد. عنوان هر heading جهت خود را با `dir="auto"`/`unicode-bidi: isolate` حفظ می‌کند؛ جای درخت به جهت UI وابسته است. ارتفاع ردیف حداقل `34px` و ارتفاع سطر `1.6` است. نام طولانی در حداکثر دو سطر نمایش داده می‌شود و متن کامل در tooltip/دسترسی کمکی باقی می‌ماند.

متادیتا property grid است، نه لیست کارت‌های مستقل: Title، Subtitle و Author ردیف‌های اطلاعات اصلی‌اند؛ Language، Direction و TOC ردیف‌های زبان و ساختار. برچسب کنار control قرار می‌گیرد؛ هر ردیف حداقل `44px` ارتفاع دارد و کنترل `32px` است. متن راهنما با ارتفاع سطر `1.6` به‌طور طبیعی می‌شکند. از border دور هر ردیف استفاده نمی‌شود؛ پیش از TOC یک خط جداکنندهٔ معنایی کافی است.

```css
#frontmatter-form {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  min-block-size: 0;
  overflow: hidden;
}
.property-grid-body { overflow-y: auto; padding: 0 12px 16px; }
.property-grid-body > label:not(.toggle) {
  display: grid;
  grid-template-columns: minmax(64px, 30%) minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-block-size: 44px;
  padding-block: 6px;
  margin: 0;
}
.property-grid-footer {
  min-block-size: 52px;
  padding: 10px 12px;
  background: var(--ui-panel-soft);
  border-block-start: 1px solid var(--ui-border);
}
```

Apply در footer متصل به همین فرم است و همراه اسکرول بدنه ناپدید نمی‌شود. این دکمه فقط متادیتا را به buffer سند اعمال می‌کند؛ نام، پیام و حالت dirty باید همین معنا را منتقل کنند. disabled/read-only، structured front matter و Undo رفتارهای موجود را حفظ می‌کنند. ساختار DOM دقیق این نقش‌ها در `property-panels.css` و فرم موجود `#frontmatter-form` تطبیق داده می‌شود؛ فرم دوم یا buffer موازی ایجاد نشود.

### ادیتور، Preview و جزئیات

Write = ویرایش Markdown با قالب درجا؛ Source = ویرایش مستقیم syntax؛ Read = خواندن غیرقابل‌ویرایش. Side preview یک انتخاب چیدمان برای همان محتوای رندرشده است. در هر دو نمای خواندن و کناری، `.document-content` و renderer مشترک استفاده شود؛ عنوان، code، جدول و math یک قرارداد دارند. کنترل‌های ویرایشی که فقط در Write معنی دارند داخل Read پنهان یا غیرفعال‌اند.

در حالت Readable، معیار هدف `70ch` با سقف عملی `760px` و padding `24–36px` است. `ch` عرض صفر لاتین است و تعداد دقیق حروف فارسی را تضمین نمی‌کند؛ آزمون بصری فارسی و zoom لازم است. Full width یک انتخاب معتبر برای بررسی جدول، مقایسه و مرور سریع است و باید همهٔ عرض آزادشده را استفاده کند. تغییر طراحی نباید انتخاب ذخیره‌شدهٔ Full width را بی‌اجازه به Readable تبدیل کند. بزرگ‌نمایی سند مستقل و با Ctrl+/− و reset به ۱۰۰٪ باقی می‌ماند.

جداکنندهٔ پنل: خط دیداری `1px`، ناحیهٔ گرفتن `10–12px` بدون fill نارنجی ضخیم و بدون grip میانی. hover می‌تواند همان خط را روشن کند. در drag، cursor resize و خط یک‌پیکسلی کافی است؛ Escape اندازهٔ آغاز را برمی‌گرداند و keydownهای جهت‌نما/Home/End باید باقی بمانند.

Scrollbar: track شفاف، thumb کم‌رنگ و گوشهٔ شفاف. مرورگر و تنظیم Windows تعیین می‌کنند scrollbar واقعاً overlay باشد یا فضا رزرو کند؛ CSS نباید به وعدهٔ overlay اجباری وابسته باشد. عرض فیزیکی `6px` با border شفاف `1px`، thumb قابل مشاهدهٔ حدود `4px` می‌دهد. در hover یا drag، thumb کمی پررنگ‌تر شود؛ آن را کامل نامرئی نکنید چون قابلیت کشف و گرفتن از بین می‌رود.

```css
* { scrollbar-width: thin; scrollbar-color: var(--ui-scrollbar-thumb) transparent; }
::-webkit-scrollbar { inline-size: 6px; block-size: 6px; }
::-webkit-scrollbar-track, ::-webkit-scrollbar-corner { background: transparent; }
::-webkit-scrollbar-thumb {
  border: 1px solid transparent;
  border-radius: 8px;
  background: var(--ui-scrollbar-thumb);
  background-clip: padding-box;
}
::-webkit-scrollbar-thumb:hover { background-color: color-mix(in srgb, var(--ui-muted) 55%, transparent); }
```

## ۴. BiDi و CSS نمایش Markdown

### چهار جهت مستقل

۱) زبان و جهت پوسته، ۲) جهت غالب سند، ۳) جهت هر پاراگراف، و ۴) جهت کد چهار مفهوم مستقل‌اند. `html[dir=rtl]` نباید روی همهٔ متن‌ها، جدول‌ها و سورس `text-align: right` تحمیل کند. از propertyهای منطقی `inline-start/end` برای UI استفاده شود؛ برای code و شمارهٔ سطر جهت ثابت LTR باقی بماند.

```css
.document-content { text-align: start; }
.document-content :is(p, li, blockquote, th, td) { unicode-bidi: plaintext; }
.document-content :not(pre) > code,
.codemirror-mount .cm-md-inline-code,
.codemirror-mount .cm-md-table code {
  direction: ltr;
  unicode-bidi: isolate;
}
.document-content pre,
.document-content pre code,
.codemirror-mount .cm-code-line {
  direction: ltr;
  unicode-bidi: isolate;
  text-align: left;
  tab-size: 4;
}
```

`isolate` برای یک قطعهٔ code مرز جهت می‌سازد؛ `bidi-override` ممنوع است چون ترتیب واقعی نویسه‌ها و punctuation را به‌هم می‌ریزد. فرمول هم در محدودهٔ LTR مستقل می‌ماند. رشتهٔ قابل‌کپی باید دقیقاً همان متن سند باشد؛ برای اصلاح ظاهری از افزودن LRM/RLM مخفی به Markdown استفاده نشود.

### کد در جدول: شناسه یک واحد است

قانون شکستِ `anywhere` از جدول و code حذف می‌شود. نثر سلول می‌تواند بین کلمه‌ها یا در یک URL بسیار طولانی شکسته شود؛ `AdaptiveCruiseTest`، `BrakeController` و `AutoDriver` داخل code باید یک قطعهٔ اتمی بمانند. فضای لازم به عرض جدول منتقل می‌شود و ظرف جدول در همان پنل اسکرول افقی می‌گیرد.

```css
.document-content table:not(.codehilitetable):not(.highlighttable),
.codemirror-mount .cm-md-table table {
  table-layout: auto;
  word-break: normal;
  overflow-wrap: normal;
}
.document-content table:not(.codehilitetable):not(.highlighttable) :is(th, td),
.codemirror-mount .cm-md-table :is(th, td) {
  min-inline-size: 8ch;
  max-inline-size: 42ch;
  white-space: normal;
  word-break: normal;
  overflow-wrap: break-word;
}
.document-content table :not(pre) > code,
.codemirror-mount .cm-md-table code {
  display: inline-block;
  direction: ltr;
  unicode-bidi: isolate;
  white-space: pre;
  word-break: normal;
  overflow-wrap: normal;
  max-inline-size: none;
}
.document-content .table-wrap,
.document-content table,
.codemirror-mount .cm-md-table {
  max-inline-size: 100%;
  overscroll-behavior-inline: contain;
}
.document-content .table-wrap { overflow-x: auto; }
```

جدول‌های مخصوص syntax highlighting از این قواعد جدول داده خارج‌اند. به code در نثر معمولیِ بسیار باریک می‌توان اجازهٔ رفتار متفاوت داد؛ nowrap فقط در table موردنیاز و قطعهٔ کد اعمال شود، نه روی کل `.document-content`. اسکرول افقی باید در خود جدول بماند؛ `document.documentElement.scrollWidth` از عرض viewport بیشتر نشود.

### Gutter سورس

شمارهٔ سطر متعلق به «جهت پایهٔ سند» است، نه پاراگراف زیر caret و نه زبان رابط. برای سند غالباً فارسی، gutter در سمت راست قرار می‌گیرد؛ برای سند انگلیسی در چپ. هر بار حرکت caret نباید آن را از طرفی به طرف دیگر بپراند. خط‌های کد، جدول و لاتین در سند فارسی همچنان decoration جهت خود را دارند. انتخاب/حرکت caret و مختصات selection CodeMirror باید با همان base direction آزموده شوند.

اتصال داده به CSS از attribute اختصاصی `data-source-direction="rtl|ltr"` روی `.cm-editor` انجام می‌شود. این attribute فقط برای Source است. ترتیب تصمیم در `source-direction.mjs`: نخست جهت صریح front matter، سپس زبان صریح غیرـ`auto`، سپس شمارش حروف نثر در ۳۲۷۶۸ واحد UTF-16 آغاز سند. fences، کد تورفته، کد درون‌خطی و URLها از شمارش غالب نثر خارج‌اند. تساوی یا متن خالی به LTR می‌رود. این تشخیص جهتِ پایه برای فارسی/انگلیسی است؛ جایگزین الگوریتم کامل BiDi هر پاراگراف نیست و تنظیمات پروژهٔ موتور PDF مستقیماً به آن تزریق نمی‌شود.

```css
.codemirror-mount .cm-editor[data-source-direction="rtl"] .cm-scroller { direction: rtl; }
.codemirror-mount .cm-editor[data-source-direction="ltr"] .cm-scroller { direction: ltr; }
.codemirror-mount .cm-editor[data-source-direction] .cm-lineNumbers .cm-gutterElement {
  direction: ltr;
  unicode-bidi: isolate;
  font-variant-numeric: tabular-nums;
}
```

از `row-reverse` روی `.cm-scroller`، translate دلخواه gutter یا position:absolute شماره‌ها استفاده نشود؛ این‌ها مدل اندازه‌گیری native ادیتور را از نمایش جدا می‌کنند. تغییر زبان UI نباید gutter سند را جابه‌جا کند.

### معیار پذیرش و جای کد

| بخش | محل مالکیت | آزمون لازم |
| --- | --- | --- |
| پوسته، توکن، Home/Export و overflow | `shell-system.css` و کنترل‌کنندهٔ DOM موجود | ۱ تا ۴ پنل، header برابر، عدم wrap، یک فرمان/یک عنصر، حفظ فوکوس و محتوای سند |
| segmentها، outline و property form | `property-panels.css` | RTL/LTR، عنوان طولانی، پنل کم‌عرض، footer قابل دسترس، structured metadata و Undo |
| code/table و جهت سورس | `bidi-layout.css` و adapter ادیتور | شناسهٔ طولانی، zoom، جدول عریض، gutter فارسی در UI انگلیسی و برعکس، selection و Undo |
| تب و مسیر | render helper مشترک | نام فایل قابل‌فهم، tooltip کامل، حفظ مسیر اصلی و تمایز دو نام برابر |
| scrollbar و divider | توکن مشترک و style پوسته | گرفتن با اشاره‌گر، keyboard resize، Escape/lost-capture، track شفاف، مرز یک‌پیکسل |

پذیرش باید در هر دو زبان رابط، هر دو پوسته و با حداقل viewportهای `1920×1080`، `1440×900`، `1108×900`، `768×1024` و `360×800` انجام شود. حالت بحرانی: چهار پنل باز، چهار فایل با نام بلند، متادیتا، جدول فارسی با code لاتین و متن در zoom برابر ۱۰۰٪ و ۱۵۰٪. ارتفاع ردیف‌ها با `getBoundingClientRect()` مقایسه شود؛ «در تصویر خوب دیده می‌شود» به‌تنهایی کافی نیست. برای جدول، مختصات تک‌تک حروف شناسه باید روی یک سطر باشد؛ برای سورس، سمت gutter و حرکت caret، copy و انتخاب واقعی بررسی شوند.

تعداد فایل‌های CSS فعلی زیاد است و قواعد چند نسل در `workspace.css` باقی مانده‌اند. سه فایل مالکیت جدید در انتهای cascade بارگیری می‌شوند؛ هر قاعده باید نقش روشن داشته باشد. حذف تدریجی قواعد مغلوب‌شده فقط پس از سنجش رفتار و حفظ آزمون‌های قبلی انجام شود. این قرارداد مجوز بازنویسی یکبارهٔ ادیتور، حذف قابلیت‌های کاربردی یا ادعای رفع همهٔ اسناد ممکن نیست.

در این تغییر، قواعد container قدیمی که toolbar را به چند سطر می‌بردند حذف شدند. منوی سرریز، همان عناصر DOM را منتقل می‌کند؛ منوی قالب‌بندی با «گزینه‌های محیط کار» و ابزارهای سراسری برنامه، عنوان و آیکون متفاوت دارد. بازکردن popup از سرریز، والد را پس از اندازه‌گیری anchor می‌بندد؛ Escape به یک کنترل قابل‌دیدن برمی‌گردد. در خروجی، عرض gutter واقعیِ scrollbar اندازه‌گیری و به dock و عنوان اعمال می‌شود تا لبه‌های outer box با دو ستون محتوایی یکسان بمانند.

### شواهد اجرای این قرارداد

گزارش‌های تولیدی در `build/design-system/` قرار دارند و وارد Git نمی‌شوند. فایل‌ها و پروفایل‌های شخصی کاربر ورودی آزمون نیستند.

| بررسی | نتیجه |
| --- | --- |
| مجموعهٔ Node | ۳۴۸ آزمون موفق؛ `node-final.log`؛ پوشش قبلی جهت بلوک‌ها نیز حفظ شده است |
| Python دسکتاپ و منابع GUI | ۱۰۸ آزمون موفق؛ `python-final.log` |
| معماری پوسته | شش ترکیب زبان/پوسته/عرض از ۳۶۰ تا ۱۹۲۰ پیکسل موفق؛ `shell-final/report.json`؛ دو keyline، عدم wrap/هم‌پوشانی، کنترل Read، تب ثابت، عرض حداکثری هر سه پنل، overflow و لبه‌های خروجی |
| پنل مشخصات و ناوبری | چهار حالت چهارپنلی موفق؛ `property-panels-four-pane/report.json`؛ ستون ۲۴۸ پیکسلی، Apply ثابت، Undo دقیق و مسیر کوتاه با tooltip کامل |
| BiDi و شناسهٔ جدول | چهار حالت موفق؛ `bidi/report.json`؛ نام کد روی یک خط، اسکرول محلی، gutter سمت سند، کلیک دقیق نویسه‌های کد و Undo |
| جهت سورس قبلی | ۲۸ بررسی موفق؛ `source-direction/report.json` |
| هندسهٔ انتخاب | ۵۷۶ حالت واقعی موفق؛ `selection-final/report.json`؛ رنگ اضافی، شکاف، حاشیه و جهت انتخاب بررسی می‌شوند |
| تعامل ادیتور | چهار حالت موفق؛ `interactions/report.json`؛ فرمول جدول، سلول، انتخاب، پنل، resize و Escape |
| جست‌وجو و تصاویر | شش حالت موفق؛ `find-images/report.json`؛ فوکوس، جایگزینی، رنگ amber و مرز بارگیری تصویر |
| رفتار عمومی و جدول | چهار حالت رفتار و دو حالت جدول موفق؛ `editor-behavior-regression/` و `table-workspace-regression/` |
| دسترسی‌پذیری ساختاری و منابع | `accessibility/` و `verify_desktop_frontend.py` موفق |

CSS درون‌خطی CodeMirror تنها با `unicode-bidi:isolate` کامل نمی‌شود؛ همان محدوده باید در `EditorView.bidiIsolatedRanges` اعلام شود تا مختصات caret با مرورگر یکسان بماند. همچنین markهای صرفاً بصری از `atomicRanges` خارج شدند؛ کلیک در وسط کد درون‌خطی اکنون به همان نویسه می‌رسد و به لبهٔ کل عبارت نمی‌پرد.

### قرارداد حالت و سطح مشترک — بازبینی ۵ نوامبر

تعریف مشترک تا زمانی که در cascade نهایی اعمال نشود کافی نیست. علت تفاوت هاور Find و Text appearance این بود که زمینهٔ شفافِ `.document-toolbar .toolbar-icon-button` قاعدهٔ هاور عمومی را مغلوب می‌کرد، ولی دکمهٔ appearance از گروه دیگری زمینه می‌گرفت. مالکیت حالت فرمان‌های خنثی اکنون در `shell-system.css` مشترک است؛ همان عناصر در منوی سرریز نیز از این قرارداد پیروی می‌کنند:

| نقش | قرارداد واقعی |
| --- | --- |
| فرمان خنثی | زمینهٔ شفاف، شعاع `6px`، در نوار ابزار ارتفاع `28px` |
| hover فرمان فعال‌پذیر | `--ui-control-hover`، در پوستهٔ تیره `#18181B`، متن اصلی |
| toggle انتخاب‌شده / popup باز | amber نرم و متن amber؛ hover این معنا را حذف نمی‌کند |
| disabled | فاقد hover فعال؛ رفتار و نشانگر غیرفعال حفظ می‌شود |
| فوکوس صفحه‌کلید | outline دوپیکسلی amber، داخل ناحیهٔ کنترل |
| Files و Inspector | هر دو `--ui-surface-navigation`، در تیره `#09090B`؛ header و footer هم‌سطح با بدنه |
| منو و دیالوگ شناور | `--ui-surface-floating`، در تیره `#18181B` |

شعاع‌های مستقل `9px` و `7px` در Find و کنترل تصویر به توکن‌های `6px` و `8px` تبدیل شدند. آزمون پوسته با hover واقعی، پس از پایان transition، رنگ نهایی Find، appearance، راهنمای نما، Insert، Focus و Inspector را می‌سنجد؛ برابر بودن سطوح دو پنل، حفظ حالت انتخاب و فوکوس صفحه‌کلید نیز بررسی می‌شوند. این بررسی روی پوستهٔ روشن و تیره و رابط فارسی و انگلیسی اجرا شده است. گزارش تازهٔ `mode-parity-final/report.json` نیز برابری Read و Side preview را در اندازه‌های ۶۰، ۱۰۰ و ۲۰۰ درصد تأیید می‌کند؛ selector وضعیت Read با جای فعلی آن در نوار ابزار هماهنگ شده است.
