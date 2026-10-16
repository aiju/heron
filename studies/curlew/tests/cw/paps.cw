-- Partial applications applied through unknown calls: every split of a
-- function's arguments between the partial application and the call
-- (ap_N's fast path and the general apply), and over-saturated calls.

f2 :: Int -> Int -> Int
f2 a b = a * 10 + b

f5 :: Int -> Int -> Int -> Int -> Int -> Int
f5 a b c d e = (((a * 10 + b) * 10 + c) * 10 + d) * 10 + e

f9 :: Int -> Int -> Int -> Int -> Int -> Int -> Int -> Int -> Int -> Int
f9 a b c d e f g h i = f5 a b c d e * 10000 + f5 0 f g h i

-- unknown calls with 1 to 4 arguments
ap1 :: (Int -> r) -> r
ap1 g = g 1
ap2 :: (Int -> Int -> r) -> r
ap2 g = g 1 2
ap3 :: (Int -> Int -> Int -> r) -> r
ap3 g = g 1 2 3
ap4 :: (Int -> Int -> Int -> Int -> r) -> r
ap4 g = g 1 2 3 4

-- the list holds partial applications made at run time
fives :: [Int -> Int]
fives = [f5 9 8 7 6, f5 9 8 7 5, f5 1 2 3 4]

main input = unlines
  [ show (ap1 (f2 4), ap2 f2, ap1 (ap1 f2))
  , show (ap1 (f5 1 2 3 4), ap2 (f5 1 2 3), ap3 (f5 1 2), ap4 (f5 1))
  , show (map ap1 fives, map (\g -> g 0) fives)
  , show (ap1 (f9 1 2 3 4 5 6 7 8), ap2 (f9 1 2 3 4 5 6 7), ap3 (f9 4 3 2 1 0 4), ap4 (f9 1 2 3 4 5))
  , show (ap1 (ap1 (f5 7 7 7)), ap2 (ap1 (f5 7 7)), ap2 (ap1 (f5 1 1)), ap2 (ap2 (f5 3)))
  , show (sum [ap2 (f5 i i i) | i <- [1..50]])
  ]
