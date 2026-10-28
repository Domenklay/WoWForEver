#include "../server/ScalingPolicy.hpp"
#include <cassert>
using namespace forever_scaling;
int main() {
    Config c;
    assert(Level(10, Rank::Normal,c)==10);
    assert(Level(60, Rank::Boss,c)==68);
    assert(Level(60, Rank::RareElite,c)==67);
    assert(Level(60, Rank::Normal,c)==60);
    assert(GuardSingleHit(9999,1000,Rank::Normal,c)==200);
    assert(GuardSingleHit(9999,1000,Rank::Elite,c)==300);
    assert(GuardSingleHit(9999,1000,Rank::RareElite,c)==400);
    assert(GuardSingleHit(9999,1000,Rank::Boss,c)==450);
    assert(GuardSingleHit(10,1000,Rank::Boss,c)==10);
    assert(GuardSingleHit(10,0,Rank::Boss,c)==0);
}
