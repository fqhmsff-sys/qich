"""Template proyek untuk 'qh new'."""

DEFAULT = {
    "src/main.qh": '''/// Menyapa seseorang.
fn greet(name: str) -> str rtrn => f"Halo, {name}!"

fn main() {
    print("Hello Qich")
    print(greet("dunia"))
}
''',
    "tests/main_test.qh": '''use mod:main

fn test_greet() {
    assert_eq(main.greet("Budi"), "Halo, Budi!")
}

fn test_aritmetika() {
    assert_eq(1 + 1, 2)
}
''',
}

AI = {
    "src/main.qh": '''use qy:model

/// Melatih jaringan kecil untuk fungsi XOR.
fn train() {
    let m = Model.sequential([Dense(2, 4, "tanh"), Dense(4, 1, "sigmoid")], 1)
    let xs = [[0, 0], [0, 1], [1, 0], [1, 1]]
    let ys = [[0], [1], [1], [0]]
    m.fit(xs, ys, 3000, 0.5)
    rtrn m
}

fn main() {
    let m = train()
    for x in [[0, 0], [0, 1], [1, 0], [1, 1]] {
        let y = m.run(x).unwrap()
        print(f"XOR({x[0]}, {x[1]}) = {round(y[0], 2)}")
    }
    m.save("xor-model.json").unwrap()
    let loaded = Model.load("xor-model.json").unwrap()
    print("model dimuat ulang:", loaded.run([1, 0]).unwrap()[0] > 0.9)
}
''',
    "tests/ai_test.qh": '''use mod:main

fn test_xor_terpelajari() {
    let m = main.train()
    assert(m.run([0, 1]).unwrap()[0] > 0.9, "XOR(0,1) harus ~1")
    assert(m.run([1, 1]).unwrap()[0] < 0.1, "XOR(1,1) harus ~0")
}

fn test_input_salah_jadi_err() {
    let m = main.train()
    assert(m.run([1, 2, 3]).is_err())
}
''',
}

WEB = {
    "src/main.qh": '''use chyb:server

/// Membangun aplikasi web (dipisah dari main agar mudah dites).
fn build_app() {
    let app = Server()
    app.get("/", fn(req) rtrn => {message: "Halo dari chyb"})
    app.get("/hello/:name", fn(req) rtrn => Response.text("Halo, " + req.params["name"] + "!"))
    app.post("/sum", fn(req) {
        let d = req.json()?
        rtrn {total: d["a"] + d["b"]}
    })
    rtrn app
}

fn main(args) {
    let app = build_app()
    app.listen(8080)
}
''',
    "tests/web_test.qh": '''use mod:main
use chyb:client

fn test_endpoint_json() {
    let h = main.build_app().start(0)
    let r = get("http://127.0.0.1:" + str(h.port) + "/").unwrap()
    h.stop()
    assert_eq(r.status, 200)
    assert_eq(r.json().unwrap()["message"], "Halo dari chyb")
}

fn test_post_dan_404_dan_header_keamanan() {
    let h = main.build_app().start(0)
    let base = "http://127.0.0.1:" + str(h.port)
    let ok = post(base + "/sum", {a: 2, b: 3}).unwrap()
    let nf = get(base + "/tidak-ada").unwrap()
    h.stop()
    assert_eq(ok.json().unwrap()["total"], 5)
    assert_eq(nf.status, 404)
    assert_eq(ok.headers["x-content-type-options"], "nosniff")
}
''',
}

APP = {
    "src/main.qh": '''use qapp:ui

/// Membangun aplikasi penghitung (declaratif; view dihitung ulang tiap render).
fn build_app() {
    let count = State(0)
    let app = App("Penghitung")
    app.view(fn() rtrn => Column([
        Text("Hitungan: " + str(count.get())),
        Row([
            Button("+1", fn() { count.set(count.get() + 1) }),
            Button("reset", fn() { count.set(0) })
        ])
    ]))
    rtrn app
}

fn main() {
    let app = build_app()
    let r = app.run(headless: false)
    if r.is_err() {
        print("Jendela tidak tersedia:", r.err().msg)
        print(app.render_text())
    }
}
''',
    "tests/app_test.qh": '''use mod:main

fn test_klik_menambah() {
    let app = main.build_app()
    app.start()
    assert(app.render_text().contains("Hitungan: 0"))
    assert(app.click("+1"))
    assert(app.click("+1"))
    assert(app.render_text().contains("Hitungan: 2"))
    app.click("reset")
    assert(app.render_text().contains("Hitungan: 0"))
}

fn test_html_aman_dari_injeksi() {
    let app = main.build_app()
    assert(!app.render_html().contains("<script>"))
}
''',
}

TEMPLATES = {"default": DEFAULT, "ai": AI, "web": WEB, "app": APP}
