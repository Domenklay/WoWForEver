#include "../server/ScalingPolicy.hpp"
#include <cassert>
using namespace forever_scaling;
int main() {
    Config c;
    assert(Level(11, 6, Rank::Normal, c) == 6);
    assert(Level(20, 6, Rank::Normal, c) == 11);
    assert(Level(20, 15, Rank::Normal, c) == 15);
    assert(Level(20, 30, Rank::Boss, c) == 30);
    assert(Level(60, 1, Rank::Normal, c) == 51);
    assert(Level(60, 1, Rank::Boss, c) == 51);
    assert(GuardSingleHit(9999,1000,Rank::Normal,c)==200);
    assert(GuardSingleHit(9999,1000,Rank::Elite,c)==300);
    assert(GuardSingleHit(9999,1000,Rank::RareElite,c)==400);
    assert(GuardSingleHit(9999,1000,Rank::Boss,c)==450);
    assert(GuardSingleHit(10,1000,Rank::Boss,c)==10);
    assert(GuardSingleHit(10,0,Rank::Boss,c)==0);
}
