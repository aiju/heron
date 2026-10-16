-- input: input/echo.txt
-- The language feature by feature: data types and deriving, classes,
-- patterns, guards, where, comprehensions, ranges, do, sections, the
-- prelude's list and character functions, show and read.

data Color = Red | Green | Blue deriving (Eq, Ord, Show, Enum)
data Shape = Circle Int | Rect Int Int deriving (Eq, Ord, Show)
data V = Int :+ Int deriving (Show, Eq)
infixl 6 :+

class Container f where
  empty :: f a
  insert' :: a -> f a -> f a
  toL :: f a -> [a]

newtypeish = 3

data Stack a = Stack [a]
instance Container Stack where
  empty = Stack []
  insert' x (Stack xs) = Stack (x : xs)
  toL (Stack xs) = xs

isEven 0 = True
isEven n = isOdd (n - 1)
isOdd 0 = False
isOdd n = isEven (n - 1)

pairs xs = [(x, y) | x <- xs, y <- xs, x < y]

lazyPat ~(a, b) = 1
strictSum :: [Int] -> Int
strictSum = go 0 where
  go !acc [] = acc
  go !acc (x:xs) = go (acc + x) xs

classify n
  | n < 0 = "neg"
  | n == 0 = "zero"
  | n < 10 = small
  | otherwise = "big"
  where small = "small"

mlookup :: Int -> Maybe Int
mlookup k = do
  a <- lookup k [(1, 10), (2, 20)]
  b <- lookup (a `div` 10) [(1, 100), (2, 200)]
  return (a + b)

main input = unlines
  [ show [Red ..]
  , show (map fromEnum [Red, Blue], [minimum [Blue, Red], maximum [Red, Green]])
  , show (Rect 1 2 < Circle 3, compare (Circle 2) (Circle 1), Circle 1 == Circle 1)
  , show (3 :+ (-4), (1 :+ 2) == (1 :+ 2))
  , show (toL (insert' 1 (insert' 2 empty) :: Stack Int))
  , show (isEven 10, isOdd 7)
  , show (pairs [1,2,3])
  , show (lazyPat undefined, strictSum [1..100])
  , show (map classify [-5, 0, 5, 50])
  , show (mlookup 1, mlookup 2, mlookup 3)
  , show [1,3..11] ++ show [10,8..1] ++ show (take 5 [7..])
  , show "a \"quoted\"\nstring" ++ show 'c' ++ show '\''
  , show (words "  hello   world  ", unwords ["a","b"], lines "x\ny\n")
  , show (sort [5,2,8,1,9,3], nub [1,1,2,3,2], reverse "abc")
  , show (divMod (-7) 2, quotRem (-7) 2, (-7) `mod` (-2), 2 ^ 10)
  , show (zip3 [1,2] "ab" [True,False], unzip [(1,'a'),(2,'b')])
  , show (let (q, r) = 17 `divMod` 5 in q * 10 + r)
  , show (fromMaybe 0 Nothing, maybe 1 (+1) (Just 5), either show (map toUpper) (Right "x" :: Either Int String))
  , show (concat [[1],[2,3]], concatMap show [1,2,3]) ++ show (and [], or [True], all even [2,4], any odd [2,4])
  , show (takeWhile (< 3) [1..], dropWhile (< 3) [1..5], span even [2,4,5,6], break (== ' ') "ab cd")
  , show (iterate (*2) 1 !! 10, length (replicate 5 'x'), take 7 (cycle [1,2,3]))
  , show (foldr (-) 0 [1,2,3], foldl (-) 0 [1,2,3], scanl (+) 0 [1,2,3], scanr (+) 0 [1,2,3])
  , show (readInt "  -123", readInt "42", gcd 12 18, lcm 4 6)
  , show (fmap (+1) (Just 1), [1,2] >>= \x -> [x, x * 10], sequence [Just 1, Just 2])
  , show (transpose ["abc", "de", "f"], intercalate ", " ["a", "b", "c"])
  , show (succ 'a', pred 10, ['a'..'e'], show (Just (-3)))
  , show (length input, take 20 input)
  ]
