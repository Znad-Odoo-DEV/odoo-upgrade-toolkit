  const ADEF = { 'Pipe Size': ['select', 10], 'Thread Size': ['radio', 20], 'Angle': ['radio', 30], 'Material': ['pills', 40], 'Type': ['select', 50], 'Brand': ['pills', 60], 'Junction Type': ['pills', 70], 'Air Type': ['pills', 80], 'Cores': ['radio', 90], 'Cable Size': ['select', 100], 'Size': ['select', 110], 'Diameter': ['select', 120], 'Rebar Diameter': ['select', 130], 'Length': ['select', 140], 'Width': ['select', 150], 'Thickness': ['select', 160], 'Capacity': ['radio', 170], 'Grade': ['pills', 180], 'Temperature': ['radio', 190], 'Colour': ['color', 200], 'Model': ['select', 210], 'Pack': ['select', 220], 'Power': ['select', 230], 'Steps': ['select', 240], 'Weight': ['select', 250], 'Volume': ['select', 260] };
  // an attribute missing on this database is created as dynamic (never 'always': that would generate variants by itself)
  X.attr = async (name) => { if (X.attrCache[name]) return X.attrCache[name];
    let a = (await call('product.attribute', 'search_read', [[['name', '=ilike', name]]], { fields: ['create_variant'], context: CTX }))[0];
    if (!a) { if (!ADEF[name]) throw new Error(`attribute ${name} not in the catalogue`);
      a = { id: await call('product.attribute', 'create', [{ name, create_variant: 'dynamic', display_type: ADEF[name][0], sequence: ADEF[name][1] }], { context: CTX }), create_variant: 'dynamic' };
      X.push({ kind: 'attribute created', name, id: a.id }); }
    if (a.create_variant !== 'dynamic') throw new Error(`attribute ${name} is ${a.create_variant}, must be dynamic`);
    const vals = await call('product.attribute.value', 'search_read', [[['attribute_id', '=', a.id]]], { fields: ['name'], context: CTX });
    return (X.attrCache[name] = { id: a.id, vals: Object.fromEntries(vals.map(v => [v.name, v.id])) }); };
