import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]
MODULE=ROOT/'mods/forever-subclass'


def load_injector():
    path=ROOT/'scripts/inject-subclass.py'
    spec=importlib.util.spec_from_file_location('subclass_injector_deploy_test',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SubclassDeployAdapterTests(unittest.TestCase):
    def test_generated_server_has_native_temporary_spells_hidden_powers_and_safe_pet_stable(self):
        injector=load_injector()
        with tempfile.TemporaryDirectory() as temp:
            core=Path(temp)
            custom=core/'src/server/scripts/Custom'
            custom.mkdir(parents=True)
            (custom/'custom_script_loader.cpp').write_text(
                'void AddClassicScripts();\n'
                'void AddCustomScripts()\n'
                '{\n'
                '    AddClassicScripts();\n'
                '}\n'
            )
            injector.inject(core,MODULE)
            cpp=(custom/'ForeverSubclass/ForeverSubclass.cpp').read_text()
            self.assertIn('p->AddTemporarySpell(newSpell);',cpp)
            self.assertIn('p->RemoveTemporarySpell(oldSpell);',cpp)
            self.assertIn('SyncHiddenSubclassPowers',cpp)
            self.assertIn('p->SetMaxPower(power,maximum*scale);',cpp)
            self.assertIn('CaptureHiddenSubclassPower',cpp)
            self.assertIn('AfterCast+=SpellCastFn(spell_forever_subclass::CapturePower)',cpp)
            self.assertIn('p->GetOrInitPetStable();',cpp)
            self.assertIn('creatureTemplate->IsTameable(false,creatureDifficulty)',cpp)
            self.assertIn('new ForeverSubclassCommandScript();',cpp)
            self.assertEqual(cpp.count('new ForeverSubclassCommandScript();'),1)

            header=(custom/'ForeverSubclass/forever_subclass/SubclassSystem.hpp').read_text()
            self.assertIn('subclassUnlockPrimaryLevel = 10;',header)


if __name__=='__main__':
    unittest.main()
