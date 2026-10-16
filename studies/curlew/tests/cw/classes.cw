-- Classes of one's own: superclasses, defaults, instances with contexts,
-- constrained and polymorphic recursion, a Functor and Monad for a type
-- of one's own, and overloaded functions used at several types.

class Shape a where
  area :: a -> Int
  name :: a -> String
  describe :: a -> String
  describe x = name x ++ " of area " ++ show (area x)

class Shape a => Solid a where
  volume :: a -> Int -> Int
  volume x h = area x * h

data Square = Square Int
data Rect = Rect Int Int

instance Shape Square where
  area (Square s) = s * s
  name _ = "square"

instance Shape Rect where
  area (Rect w h) = w * h
  name _ = "rectangle"
  describe r = "a " ++ name r ++ ", " ++ show (area r)

instance Solid Square
instance Solid Rect where
  volume r h = 2 * area r * h

data Pair a = Pair a a deriving (Show, Eq, Ord)

instance Functor Pair where
  fmap f (Pair x y) = Pair (f x) (f y)

data Writer a = Writer a [String]

instance Monad Writer where
  return x = Writer x []
  Writer x w >>= f = case f x of Writer y w' -> Writer y (w ++ w')

tell :: String -> Writer ()
tell s = Writer () [s]

logged :: Int -> Writer Int
logged n = do
  tell ("got " ++ show n)
  let m = n * 2
  tell ("doubled " ++ show m)
  return (m + 1)

class Container f where
  cmap :: (a -> b) -> f a -> f b
  toList' :: f a -> [a]

instance Container Pair where
  cmap = fmap
  toList' (Pair x y) = [x, y]

total :: (Container f) => f Int -> Int
total c = sum (toList' c)

largest :: Ord a => [a] -> a
largest = foldr1 max

data Nested a = Flat a | Nest (Nested [a])

depth :: Nested a -> Int
depth (Flat _) = 0
depth (Nest n) = 1 + depth n

pairs :: (Eq a, Show a) => [a] -> [String]
pairs xs = [show x ++ "=" ++ show y | x <- xs, y <- xs, x == y]

main input = unlines
  [ describe (Square 3), describe (Rect 2 5)
  , show (volume (Square 2) 10, volume (Rect 2 3) 10)
  , show (fmap (* 2) (Pair 3 4), Pair 1 2 < Pair 1 3, Pair 'a' 'b' == Pair 'a' 'b')
  , show (total (cmap (+ 1) (Pair 10 20)))
  , case logged 20 of Writer v w -> show v ++ " " ++ show w
  , show (largest [3, 1, 4, 1, 5], largest "curlew", largest [[1, 2], [3], [1, 5]])
  , show (depth (Nest (Nest (Flat [[1 :: Int]]))))
  , show (pairs [1, 2, 3], pairs "ab")
  , show (compare (Just 3) Nothing, max (Left 1) (Right 'x' :: Either Int Char), [LT ..])
  ]
