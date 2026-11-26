"""Kombinierte Einheitenfilter und automatische Lerngruppen über Schuljahresgrenzen."""
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node fehlt')
def test_unit_filters_resolve_groups_and_combine_criteria():
    script = r'''
      import assert from 'node:assert/strict';
      import { readFileSync } from 'node:fs';
      const url = text => 'data:text/javascript;base64,' + Buffer.from(text).toString('base64');
      const source = readFileSync('src/material_ui/static/unit-filters.js', 'utf8')
        .replace("'./ui-utils.js'", JSON.stringify(url(readFileSync('src/material_ui/static/ui-utils.js', 'utf8'))))
        .replace("'./unit-data.js'", JSON.stringify(url(readFileSync('src/material_ui/static/unit-data.js', 'utf8'))));
      const { passesFilters, filtersActive, unitGroups } = await import(url(source));
      const unit = {fach: 'mathematik', klasse: 'klasse-05', data: {tags: ['test'], einsatz: [
        {datum: '2026-07-31'}, {datum: '2026-08-01'}, {datum: '2026-09-01', lerngruppe: '05B'}]}};
      const groupDefaults = [{grade: '05', year: '2025/2026', group: '05A'},
        {grade: '05', year: '2026/2027', group: '05C'}];
      assert.deepEqual(unitGroups(unit, groupDefaults), ['05A', '05C', '05B']);
      const filters = {groupDefaults, schoolYear: '2026/2027', subjectFilter: 'mathematik',
        groupFilter: '05C', tagFilter: 'test', completionFilter: 'open'};
      assert.equal(passesFilters(unit, filters), true);
      assert.equal(passesFilters(unit, {...filters, groupFilter: '5 c'}), true);
      for (const mismatch of [{subjectFilter: 'deutsch'}, {groupFilter: '05A'}, {tagFilter: 'other'},
        {completionFilter: 'done'}, {onlyUndated: true}]) {
        assert.equal(passesFilters(unit, {...filters, ...mismatch}), false);
      }
      const undated = {...unit, data: {...unit.data, einsatz: []}};
      assert.equal(passesFilters(undated, {...filters, onlyUndated: true}), true);
      assert.equal(passesFilters(unit, {}), true);
      for (const value of [{subjectFilter: 'mathematik'}, {groupFilter: '05C'}, {onlyUndated: true}])
        assert.equal(filtersActive(value), true);
      assert.equal(filtersActive({}), false);
    '''
    subprocess.run(['node', '--input-type=module', '-e', script], check=True, capture_output=True, text=True, timeout=15)
