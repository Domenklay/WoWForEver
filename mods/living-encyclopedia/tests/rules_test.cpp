#include "../server/EncyclopediaRules.h"
#include <cassert>
int main() {
    using namespace encyclopedia;
    Config cfg;
    State s{0, 100, 0, 0};
    Context c;
    assert(Regen(s, c, cfg, 1) == 5);
    c.inCombat = true;
    assert(Regen(s, c, cfg, 1) == 1);
    c.groupSize = 5;
    assert(!Allowed(c));
    assert(Regen(s, c, cfg, 1) == 0);
    c.groupSize = 1;
    s.mana = 100;
    assert(Shield(s,c,cfg,30000,700,1000,9999,50) == 300);
    assert(s.mana == 50);
    assert(Heal(s,c,cfg,30000,400,1000,9999,50,false) == 250);
    assert(s.mana == 0);
    s.mana = 100;
    assert(Heal(s,c,cfg,51000,400,1000,9999,50,true) == 400);
    c.inPvp = true;
    assert(Shield(s,c,cfg,90000,100,1000,100,10) == 0);
    assert(Heal(s,c,cfg,90000,100,1000,100,10,true) == 0);
    return 0;
}
