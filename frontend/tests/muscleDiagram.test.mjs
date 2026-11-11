import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/MuscleDiagram.tsx', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } })
const module = { exports: {} }
const anatomySource = readFileSync(new URL('../src/anatomyPaths.ts', import.meta.url), 'utf8')
const anatomyCompiled = ts.transpileModule(anatomySource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
const anatomyModule = { exports: {} }
new Function('require', 'module', 'exports', anatomyCompiled.outputText)(createRequire(import.meta.url), anatomyModule, anatomyModule.exports)
const requireModule = name => name === './anatomyPaths' ? anatomyModule.exports : createRequire(import.meta.url)(name)
new Function('require', 'module', 'exports', compiled.outputText)(requireModule, module, module.exports)
const { muscleLoads, zoneTone } = module.exports

const strength = (primary_group, secondary_groups, sets_count, skipped = false) =>
  ({ kind: 'strength', primary_group, secondary_groups, sets_count, skipped })

test('the saved workout snapshot adds direct and half indirect sets', () => {
  const loads = muscleLoads([
    strength('Грудь', ['Трицепс'], 3),
    strength('Верх груди', ['Трицепс'], 2),
    strength('Бицепс', ['Предплечья'], 4, true),
    { kind: 'cardio', primary_group: 'Грудь', secondary_groups: ['Спина'], sets_count: 20 },
  ])
  assert.deepEqual(loads.upperChest, { direct: 5, indirect: 0 })
  assert.deepEqual(loads.chest, { direct: 3, indirect: 0 })
  assert.deepEqual(loads.triceps, { direct: 0, indirect: 2.5 })
  assert.equal(loads.biceps, undefined)
  assert.equal(zoneTone(loads.upperChest), '#ee594b')
  assert.equal(zoneTone(loads.triceps), '#65acf0')
})

test('broad back covers detailed regions and direct work outranks indirect', () => {
  const loads = muscleLoads([strength('Спина', ['Ромбовидные'], 4), strength('Трапеция', [], 2)])
  assert.equal(loads.rhomboids.direct, 4)
  assert.equal(loads.rhomboids.indirect, 0)
  assert.equal(loads.traps.direct, 6)
  assert.equal(zoneTone({ direct: 0, indirect: 4 }), '#3689dc')
  assert.equal(zoneTone({ direct: 0, indirect: 1 }), '#a2cefa')
})
