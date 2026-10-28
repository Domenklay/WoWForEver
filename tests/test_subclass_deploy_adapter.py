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
    def test_generated_server_has_authoritative_casts_native_powers_and_safe_pet_stable(self):
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
            # The maintained injector explicitly rejects the removed temporary-spell
            # implementation. Casts use the server request path and real class slots
            # when available; classes without a slot retain server-side pools.
            self.assertNotIn('AddTemporarySpell(',cpp)
            self.assertNotIn('RemoveTemporarySpell(',cpp)
            self.assertIn('HasNativePowerSlot(p,def.root.power)',cpp)
            self.assertIn('p->ModifyPower(def.root.power,-cost*',cpp)
            self.assertIn('else e.pools[def.root.power].current=',cpp)
            self.assertIn('std::any_cast<CastTag>',cpp)
            self.assertIn('TRIGGERED_IGNORE_POWER_COST).SetCustomArg(CastTag{})',cpp)
            self.assertIn('if(!Allowed(p,e,id))',cpp)
            self.assertIn('p->GetOrInitPetStable();',cpp)
            self.assertIn('CREATURE_STATIC_FLAG_TAMEABLE',cpp)
            self.assertIn('CREATURE_STATIC_FLAG_3_TAMEABLE_EXOTIC',cpp)
            self.assertIn('p->CreateTamedPetFrom(creature,HunterTameSpell)',cpp)
            self.assertIn('new ForeverSubclassCommandScript();',cpp)
            self.assertEqual(cpp.count('new ForeverSubclassCommandScript();'),1)

            header=(custom/'ForeverSubclass/forever_subclass/SubclassSystem.hpp').read_text()
            self.assertIn('subclassUnlockPrimaryLevel = 10;',header)


if __name__=='__main__':
    unittest.main()
