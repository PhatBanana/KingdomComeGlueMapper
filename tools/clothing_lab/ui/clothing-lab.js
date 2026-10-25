"use strict";
(() => {
  const q = (s) => document.querySelector(s),
    T = window.GM3D;
  let catalog = null,
    parts = new Map(),
    selection = [],
    response = null,
    serial = 0,
    running = false,
    polling = false,
    seen = 0;
  let renderer, scene, camera, controls, group, unmasked, resizeObserver;
  const colours = [
    0x64b9b1, 0xe8b46e, 0x87a8d8, 0xbb8dcc, 0xd78175, 0x9fb768, 0xd5a2be,
  ];
  const api = () => {
    if (!window.pywebview?.api)
      throw new Error(
        "Launch tools/clothing_lab_app.py to inspect installed assets.",
      );
    return window.pywebview.api;
  };
  const status = (s) => (q("#lab-status").textContent = s);
  const guard = (fn) => async () => {
    try {
      await fn();
    } catch (e) {
      status(e.message || String(e));
    }
  };
  function options(element, rows) {
    element.replaceChildren();
    for (const [value, label] of rows) {
      const o = document.createElement("option");
      o.value = value;
      o.textContent = label;
      element.append(o);
    }
  }
  function findPart(p) {
    return `${p.label} ${p.attributes.ArmorType || ""} ${p.elements.map((e) => e.EquipmentPart).join(" ")}`.toLowerCase();
  }
  function fillGarments() {
    if (!catalog) return;
    const preset = catalog.presets.find((p) => p.id === q("#lab-preset").value),
      search = q("#lab-search").value.toLowerCase();
    options(
      q("#lab-garment"),
      catalog.parts
        .filter(
          (p) =>
            p.kind === "Clothing" &&
            (!preset || p.gender === preset.gender) &&
            findPart(p).includes(search),
        )
        .map((p) => [p.id, p.label]),
    );
  }
  function fillPresets() {
    if (!catalog) return;
    const gender = q("#lab-gender").value;
    options(
      q("#lab-preset"),
      catalog.presets
        .filter((p) => gender === "All" || p.gender === gender)
        .map((p) => [p.id, `${p.label} · ${p.gender}`]),
    );
    fillGarments();
  }
  function showFindings(result) {
    q("#lab-findings").replaceChildren();
    for (const f of result.findings || []) {
      const div = document.createElement("div");
      div.className = "lab-finding " + f.severity;
      div.textContent = `${f.code}: ${f.message}${f.vertices !== undefined ? " (" + f.vertices + " vertices)" : ""}`;
      div.title = (f.components || []).join("\n");
      q("#lab-findings").append(div);
    }
    if (!(result.findings || []).length)
      q("#lab-findings").textContent =
        "No findings in the checks performed. Native rendering is not verified.";
  }
  function stack() {
    q("#lab-stack").replaceChildren();
    for (const id of selection) {
      const p = parts.get(id),
        row = document.createElement("div"),
        label = document.createElement("label"),
        box = document.createElement("input"),
        small = document.createElement("small");
      row.className = "lab-part";
      box.type = "checkbox";
      box.checked = true;
      box.dataset.part = id;
      box.addEventListener("change", guard(refresh));
      label.append(box, document.createTextNode(p.label));
      small.textContent =
        p.kind +
        " · " +
        p.elements
          .map((e) => `${e.EquipmentPart} / layer ${e.BodyLayerId ?? "?"}`)
          .join(", ");
      row.append(label, small);
      q("#lab-stack").append(row);
    }
  }
  function selected() {
    return [...q("#lab-stack").querySelectorAll("input:checked")].map(
      (e) => e.dataset.part,
    );
  }
  async function refresh() {
    const ids = selected();
    if (!ids.length) {
      response = null;
      if (group) clearMeshes();
      return;
    }
    const ticket = ++serial;
    status("Reading selected meshes and textures…");
    const r = await api().clothing_scene(ids, Number(q("#lab-lod").value));
    if (ticket !== serial) return;
    response = r;
    showFindings(r.validation);
    initRenderer();
    rebuild();
    status(
      `${r.scene.meshes.length} meshes loaded · ${r.scene.errors.length} asset errors · ${r.validation.status || "preview"}. ${r.scene.errors.map((e) => e.error).join(" ")}`,
    );
  }
  async function restore() {
    const p = catalog?.presets.find((p) => p.id === q("#lab-preset").value);
    if (!p) return;
    selection = [...p.parts];
    stack();
    fillGarments();
    await refresh();
  }
  function initRenderer() {
    if (renderer) return;
    if (!T) throw new Error("Bundled 3D renderer is unavailable");
    const viewport = q("#lab-viewport");
    renderer = new T.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = T.SRGBColorSpace;
    viewport.append(renderer.domElement);
    q("#lab-empty").hidden = true;
    scene = new T.Scene();
    scene.background = new T.Color(0x20272c);
    camera = new T.PerspectiveCamera(35, 1, 0.01, 100);
    camera.up.set(0, 0, 1);
    camera.position.set(0, 3.6, 1.2);
    controls = new T.OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0.85);
    controls.enableDamping = true;
    controls.minDistance = 0.15;
    controls.maxDistance = 15;
    scene.add(new T.HemisphereLight(0xdbe9ff, 0x766751, 2));
    const light = new T.DirectionalLight(0xffffff, 2.5);
    light.position.set(2, 3, 4);
    scene.add(light);
    const grid = new T.GridHelper(6, 30, 0x59656c, 0x35434b);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);
    group = new T.Group();
    unmasked = new T.Group();
    scene.add(group, unmasked);
    unmasked.visible = false;
    resizeObserver = new ResizeObserver(() => size());
    resizeObserver.observe(viewport);
    size();
    renderer.setAnimationLoop(draw);
  }
  function size() {
    if (!renderer) return;
    const r = q("#lab-viewport").getBoundingClientRect();
    if (!r.width || !r.height) return;
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / r.height;
    camera.updateProjectionMatrix();
  }
  function clearMeshes() {
    for (const g of [group, unmasked]) {
      while (g.children.length) {
        const m = g.children[0];
        g.remove(m);
        m.geometry.dispose();
        for (const a of Array.isArray(m.material) ? m.material : [m.material]) {
          a.map?.dispose();
          a.dispose();
        }
      }
    }
  }
  function buffer(encoded, type) {
    const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    return new type(bytes.buffer);
  }
  function boneMatrix(values) {
    return new T.Matrix4().set(
      ...values.slice(0, 4),
      ...values.slice(4, 8),
      ...values.slice(8, 12),
      0,
      0,
      0,
      1,
    );
  }
  function stressPose(row, positions) {
    const angle = (Number(q("#lab-pose").value) * Math.PI) / 180;
    if (!angle) return positions;
    const ids = buffer(row.joints, Uint16Array),
      weights = buffer(row.weights, Float32Array),
      transforms = [],
      visiting = new Set();
    function transform(index) {
      if (transforms[index]) return transforms[index];
      if (visiting.has(index)) throw new Error("Cyclic skeleton");
      visiting.add(index);
      const bone = row.bones[index],
        parent =
          bone.parent_index == null
            ? new T.Matrix4()
            : transform(bone.parent_index).clone();
      if (/forearm/i.test(bone.name) && !/twist|aux|roll/i.test(bone.name)) {
        const bind = boneMatrix(bone.bind),
          rotation = new T.Matrix4().makeRotationY(
            /left/i.test(bone.name) ? -angle : angle,
          );
        parent
          .multiply(bind)
          .multiply(rotation)
          .multiply(bind.clone().invert());
      }
      transforms[index] = parent;
      visiting.delete(index);
      return parent;
    }
    row.bones.forEach((_, i) => transform(i));
    const output = new Float32Array(positions.length),
      v = new T.Vector3();
    for (let i = 0; i < positions.length / 3; i++) {
      for (let j = 0; j < row.influences; j++) {
        const k = i * row.influences + j,
          w = weights[k];
        if (!w) continue;
        v.fromArray(positions, i * 3).applyMatrix4(transforms[ids[k]]);
        output[i * 3] += v.x * w;
        output[i * 3 + 1] += v.y * w;
        output[i * 3 + 2] += v.z * w;
      }
    }
    return output;
  }
  function makeMesh(row, index, mask, replaced = false) {
    const geometry = new T.BufferGeometry(),
      positions = stressPose(row, buffer(row.positions, Float32Array)),
      indices = buffer(row.indices, Uint32Array),
      alpha = buffer(row.alpha, Uint8Array),
      kept = [];
    geometry.setAttribute("position", new T.BufferAttribute(positions, 3));
    geometry.setAttribute(
      "uv",
      new T.BufferAttribute(buffer(row.uv, Float32Array), 2),
    );
    for (const subset of row.subsets) {
      const start = kept.length;
      for (
        let i = subset.first_index;
        i < subset.first_index + subset.num_indices;
        i += 3
      ) {
        if (
          replaced ||
          [indices[i], indices[i + 1], indices[i + 2]].some(
            (v) => ((255 ^ alpha[v]) & mask) !== 0,
          )
        )
          continue;
        kept.push(indices[i], indices[i + 1], indices[i + 2]);
      }
      geometry.addGroup(start, kept.length - start, subset.material_id);
    }
    geometry.setIndex(kept);
    geometry.computeVertexNormals();
    const mode = q("#lab-shading").value;
    const materials = row.materials.map((m) => {
      const material = new T.MeshStandardMaterial({
        color: mode === "layers" ? colours[index % colours.length] : 0xffffff,
        side: T.DoubleSide,
        roughness: 0.9,
        wireframe: mode === "wireframe",
        alphaTest: m.threshold,
        opacity: m.opacity,
      });
      material.visible = m.shader?.toLowerCase() !== "nodraw";
      if (m.image) {
        material.map = new T.TextureLoader().load(m.image);
        material.map.flipY = false;
        material.map.colorSpace = T.SRGBColorSpace;
        material.map.wrapS = material.map.wrapT = T.RepeatWrapping;
        /* Keep alpha cutouts in all diagnostic modes. */ if (mode === "layers")
          material.onBeforeCompile = (shader) => {
            shader.fragmentShader = shader.fragmentShader.replace(
              "diffuseColor *= sampledDiffuseColor;",
              "diffuseColor.a *= sampledDiffuseColor.a;",
            );
          };
      }
      return material;
    });
    const mesh = new T.Mesh(geometry, materials);
    mesh.position.x =
      (((index - (response.scene.meshes.length - 1) / 2) *
        Number(q("#lab-explode").value)) /
        100) *
      0.32;
    return mesh;
  }
  function rebuild() {
    if (!renderer || !response) return;
    clearMeshes();
    const masks = {};
    for (const id of selected()) {
      for (const name of (parts.get(id).attributes.HidingGroups || "").split(
        /\s+/,
      )) {
        const g = catalog.groups[name];
        if (g) masks[g.region] = (masks[g.region] || 0) | (1 << g.index);
      }
    }
    response.scene.meshes.forEach((row, i) => {
      group.add(
        makeMesh(
          row,
          i,
          q("#lab-masks").checked ? masks[row.element.EquipmentPart] || 0 : 0,
          q("#lab-masks").checked && row.replaced,
        ),
      );
      unmasked.add(makeMesh(row, i, 0));
    });
    q("#lab-legend").hidden = !q("#lab-compare").checked;
  }
  function draw() {
    if (!renderer || document.body.dataset.view !== "tools") return;
    controls.autoRotate = q("#lab-rotate").checked;
    controls.update();
    const width = renderer.domElement.clientWidth,
      height = renderer.domElement.clientHeight,
      compare = q("#lab-compare").checked;
    if (!width || !height) return;
    renderer.setScissorTest(compare);
    if (compare) {
      camera.aspect = width / 2 / height;
      camera.updateProjectionMatrix();
      group.visible = true;
      unmasked.visible = false;
      renderer.setViewport(0, 0, width / 2, height);
      renderer.setScissor(0, 0, width / 2, height);
      renderer.render(scene, camera);
      group.visible = false;
      unmasked.visible = true;
      renderer.setViewport(width / 2, 0, width / 2, height);
      renderer.setScissor(width / 2, 0, width / 2, height);
      renderer.render(scene, camera);
    } else {
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      group.visible = true;
      unmasked.visible = false;
      renderer.setViewport(0, 0, width, height);
      renderer.render(scene, camera);
    }
  }
  function resultRow(row) {
    const div = document.createElement("div"),
      badge = document.createElement("span"),
      label = document.createElement("span"),
      button = document.createElement("button");
    div.className = "lab-result";
    badge.textContent = row.status;
    label.textContent = row.label;
    button.className = "secondary";
    button.textContent = "Inspect";
    button.disabled = !row.selected?.length;
    button.addEventListener(
      "click",
      guard(async () => {
        selection = [...row.selected];
        stack();
        await refresh();
        showFindings(row);
        q("#lab-viewport").scrollIntoView({ block: "center" });
      }),
    );
    div.append(badge, label, button);
    q("#lab-results").append(div);
  }
  q("#lab-installed").addEventListener("click", () => {
    q("#lab-package").value =
      q("#kcd2").value.replace(/[\\/]$/, "") + "/Mods/kingdomcomegluemapper";
  });
  q("#lab-open").addEventListener(
    "click",
    guard(async () => {
      if (running) throw new Error("Stop the audit before changing packages");
      q("#lab-open").disabled = true;
      try {
        status("Indexing packaged characters…");
        catalog = await api().clothing_open(
          q("#lab-package").value.trim(),
          q("#kcd2").value.trim(),
        );
        parts = new Map(catalog.parts.map((p) => [p.id, p]));
        fillPresets();
        await restore();
        status(
          `${catalog.presets.length} character presets · ${catalog.parts.length} components · ${catalog.native_rules ? "KCD2 rules loaded" : "KCD2 rules not loaded"} · ${catalog.errors.length} catalog errors`,
        );
      } finally {
        q("#lab-open").disabled = false;
      }
    }),
  );
  q("#lab-gender").addEventListener(
    "change",
    guard(async () => {
      fillPresets();
      await restore();
    }),
  );
  q("#lab-preset").addEventListener("change", guard(restore));
  q("#lab-reset").addEventListener("click", guard(restore));
  q("#lab-search").addEventListener("input", fillGarments);
  q("#lab-add").addEventListener(
    "click",
    guard(async () => {
      const id = q("#lab-garment").value;
      if (id && !selection.includes(id)) {
        selection.push(id);
        stack();
        await refresh();
      }
    }),
  );
  q("#lab-lod").addEventListener("change", guard(refresh));
  for (const id of ["shading", "masks", "compare", "explode", "pose"])
    q("#lab-" + id).addEventListener(
      "input",
      guard(async () => rebuild()),
    );
  document.querySelectorAll("[data-lab-view]").forEach((b) =>
    b.addEventListener("click", () => {
      if (!camera) return;
      const distance = camera.position.distanceTo(controls.target),
        dir = { front: [0, 1, 0], back: [0, -1, 0], side: [1, 0, 0] }[
          b.dataset.labView
        ];
      camera.position
        .copy(controls.target)
        .add(new T.Vector3(...dir).multiplyScalar(distance));
      controls.update();
    }),
  );
  q("#lab-capture").addEventListener(
    "click",
    guard(async () => {
      if (!renderer) throw new Error("Load a character first");
      draw();
      const path = await api().clothing_capture(
        selected(),
        Number(q("#lab-lod").value),
        renderer.domElement.toDataURL("image/png"),
        {
          camera: camera.position.toArray(),
          target: controls.target.toArray(),
          shading: q("#lab-shading").value,
          compare: q("#lab-compare").checked,
          masks: q("#lab-masks").checked,
          pose: Number(q("#lab-pose").value),
          explode: Number(q("#lab-explode").value),
        },
      );
      status("Saved image and reproducible selection: " + path);
    }),
  );
  q("#lab-run").addEventListener(
    "click",
    guard(async () => {
      if (!catalog) throw new Error("Open a package first");
      const options = {
        mode: q("#lab-mode").value,
        body: q("#lab-preset").value,
        gender: q("#lab-gender").value,
        limit: Number(q("#lab-limit").value),
        offset: Number(q("#lab-offset").value),
        lod: Number(q("#lab-lod").value),
        geometry: q("#lab-geometry").checked,
        source: q("#kcd1").value.trim(),
      };
      await api().clothing_run(options);
      running = true;
      seen = 0;
      q("#lab-results").replaceChildren();
      q("#lab-run").disabled = true;
      q("#lab-open").disabled = true;
      q("#lab-stop").disabled = false;
      q("#lab-progress").textContent = "Preparing audit…";
    }),
  );
  q("#lab-stop").addEventListener(
    "click",
    guard(async () => {
      await api().clothing_cancel();
      q("#lab-progress").textContent =
        "Stopping after the current case. Completed findings will be saved.";
    }),
  );
  q("#lab-reports").addEventListener(
    "click",
    guard(async () => api().clothing_reports()),
  );
  setInterval(async () => {
    if (!running || polling) return;
    polling = true;
    try {
      const p = await api().clothing_poll(seen);
      for (const row of p.results) {
        resultRow(row);
        seen++;
      }
      q("#lab-progress").textContent =
        `${p.done} / ${p.total} cases · ${p.message || ""}`;
      if (!p.running && seen >= p.done) {
        running = false;
        q("#lab-run").disabled = false;
        q("#lab-open").disabled = false;
        q("#lab-stop").disabled = true;
        const enumeration = p.enumeration || {};
        q("#lab-progress").textContent =
          p.error ||
          `${p.cancelled ? "Stopped" : "Batch finished"} · ${JSON.stringify(p.counts || {})} · ${enumeration.next_offset ?? p.done} / ${enumeration.total ?? p.total} in plan · report: ${p.report}`;
        if (enumeration.next_offset !== undefined)
          q("#lab-offset").value = enumeration.next_offset;
      }
    } catch (e) {
      running = false;
      q("#lab-run").disabled = false;
      q("#lab-open").disabled = false;
      q("#lab-stop").disabled = true;
      status(e.message || String(e));
    } finally {
      polling = false;
    }
  }, 700);
  async function locations() {
    const d = await api().clothing_locations();
    q("#kcd1").value = d.source;
    q("#kcd2").value = d.target;
    q("#lab-package").value = d.package;
  }
  window.addEventListener("pywebviewready", guard(locations));
  if (window.pywebview?.api) guard(locations)();
})();
